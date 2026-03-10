"""
后台缓存工作线程 - 预缓存寄存器状态检查点
"""
import bisect
import time
from queue import PriorityQueue, Empty
from typing import Dict, Optional, Set, TYPE_CHECKING
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from register import Register, RegisterState

if TYPE_CHECKING:
    from lazy_parser import LazyLogParser


class CacheWorker(QThread):
    """后台缓存工作线程
    
    功能：
    1. 文件加载后自动在后台建立检查点（每500条指令一个）
    2. 用户操作时优先处理当前位置附近的缓存任务
    3. 空闲时继续构建远距离检查点
    """
    
    # 信号：检查点就绪 (checkpoint_index, RegisterState)
    checkpoint_ready = Signal(int, object)
    # 信号：特定位置缓存就绪 (index, RegisterState)
    cache_ready = Signal(int, object)
    # 信号：进度更新 (current, total)
    progress = Signal(int, int)
    # 信号：全部检查点构建完成
    all_checkpoints_ready = Signal()
    
    def __init__(self, parser: 'LazyLogParser', checkpoint_interval: int = 500):
        super().__init__()
        self.parser = parser
        self.checkpoint_interval = checkpoint_interval
        
        # 检查点缓存 {index: RegisterState}
        self.checkpoints: Dict[int, RegisterState] = {}
        # 已排序的检查点索引列表（用于二分查找）
        self._checkpoint_indices: list = []
        
        # 优先级任务队列 (priority, index)
        # priority: 0=最高（用户请求）, 1=中等（预测性缓存）, 2=低（后台检查点）
        self.task_queue: PriorityQueue = PriorityQueue()
        
        # 线程控制
        self._running = False
        self._paused = False
        self._mutex = QMutex()
        
        # 已处理的任务集合（避免重复处理）
        self._processed_checkpoints: Set[int] = set()
        
        # 当前正在构建的检查点索引
        self._current_building_index = -1
        
    def set_parser(self, parser: 'LazyLogParser'):
        """设置解析器（文件加载后调用）"""
        with QMutexLocker(self._mutex):
            self.parser = parser
            # 清空缓存
            self.checkpoints.clear()
            self._checkpoint_indices.clear()
            self._processed_checkpoints.clear()
            # 清空任务队列
            while not self.task_queue.empty():
                try:
                    self.task_queue.get_nowait()
                except Empty:
                    break
    
    def start_building_checkpoints(self):
        """开始构建所有检查点（后台任务）"""
        if not self.parser:
            return
        
        instruction_count = self.parser.get_instruction_count()
        
        # 将所有检查点任务加入队列（低优先级）
        for i in range(0, instruction_count, self.checkpoint_interval):
            if i not in self._processed_checkpoints:
                self.task_queue.put((2, i))  # 优先级2：后台检查点
        
        # 启动线程
        if not self.isRunning():
            self._running = True
            self.start()
    
    def request_cache_at(self, index: int, high_priority: bool = True):
        """请求特定位置的缓存
        
        Args:
            index: 指令索引
            high_priority: 是否高优先级（用户请求）
        """
        priority = 0 if high_priority else 1
        self.task_queue.put((priority, index))
        
        # 确保线程运行
        if not self.isRunning():
            self._running = True
            self.start()
    
    def request_range_cache(self, start: int, end: int):
        """请求一个范围内的缓存（预测性缓存）"""
        # 找到范围内的检查点
        for i in range(start, end + 1, self.checkpoint_interval):
            checkpoint = (i // self.checkpoint_interval) * self.checkpoint_interval
            if checkpoint not in self._processed_checkpoints:
                self.task_queue.put((1, checkpoint))  # 优先级1：预测性缓存
        
        if not self.isRunning():
            self._running = True
            self.start()
    
    def find_nearest_checkpoint(self, index: int) -> int:
        """二分查找最近的检查点（不超过index）
        
        Returns:
            检查点索引，如果没有则返回-1
        """
        with QMutexLocker(self._mutex):
            if not self._checkpoint_indices:
                return -1
            
            pos = bisect.bisect_right(self._checkpoint_indices, index)
            if pos > 0:
                return self._checkpoint_indices[pos - 1]
            return -1
    
    def get_checkpoint(self, index: int) -> Optional[RegisterState]:
        """获取指定检查点的状态"""
        with QMutexLocker(self._mutex):
            return self.checkpoints.get(index)
    
    def has_checkpoint(self, index: int) -> bool:
        """检查是否有指定的检查点"""
        with QMutexLocker(self._mutex):
            return index in self.checkpoints
    
    def get_checkpoint_count(self) -> int:
        """获取已构建的检查点数量"""
        with QMutexLocker(self._mutex):
            return len(self.checkpoints)
    
    def get_total_checkpoints_needed(self) -> int:
        """获取需要构建的检查点总数"""
        if not self.parser:
            return 0
        count = self.parser.get_instruction_count()
        return (count + self.checkpoint_interval - 1) // self.checkpoint_interval
    
    def pause(self):
        """暂停后台构建"""
        self._paused = True
    
    def resume(self):
        """恢复后台构建"""
        self._paused = False
    
    def stop(self):
        """停止线程"""
        self._running = False
        self.wait()
    
    def run(self):
        """线程主循环"""
        print("[CacheWorker] 线程启动")
        
        while self._running:
            # 检查是否暂停
            if self._paused:
                self.msleep(100)
                continue
            
            try:
                # 尝试获取任务（超时100ms）
                priority, index = self.task_queue.get(timeout=0.1)
            except Empty:
                # 队列为空，检查是否所有检查点已构建
                if self._all_checkpoints_built():
                    print("[CacheWorker] 所有检查点已构建完成")
                    self.all_checkpoints_ready.emit()
                    break
                continue
            
            # 检查是否已处理
            checkpoint_index = (index // self.checkpoint_interval) * self.checkpoint_interval
            
            # 高优先级任务总是处理，低优先级检查是否已处理
            if priority >= 2 and checkpoint_index in self._processed_checkpoints:
                continue
            
            # 构建缓存
            self._build_cache_to(index)
    
    def _all_checkpoints_built(self) -> bool:
        """检查是否所有检查点都已构建"""
        if not self.parser:
            return True
        
        total = self.get_total_checkpoints_needed()
        built = self.get_checkpoint_count()
        return built >= total
    
    def _build_cache_to(self, target_index: int):
        """构建缓存到指定位置"""
        if not self.parser:
            return
        
        build_start = time.time()
        
        # 找到最近的已有检查点
        nearest = self.find_nearest_checkpoint(target_index)
        
        if nearest >= 0:
            # 从最近的检查点开始
            state = self.checkpoints[nearest].copy()
            start_index = nearest + 1
        else:
            # 从头开始
            state = RegisterState()
            start_index = 0
        
        # 逐条处理指令，更新寄存器状态
        instructions_processed = 0
        for i in range(start_index, target_index + 1):
            instruction = self.parser.parse_instruction_at(i)
            if instruction:
                for change in instruction.register_changes:
                    state.update(change.register, change.new_value)
            
            instructions_processed += 1
            
            # 每到检查点就保存
            if i % self.checkpoint_interval == 0 and i not in self._processed_checkpoints:
                self._save_checkpoint(i, state.copy())
        
        # 如果目标位置正好是检查点，确保已保存
        if target_index % self.checkpoint_interval == 0:
            if target_index not in self._processed_checkpoints:
                self._save_checkpoint(target_index, state.copy())
        
        # 发送缓存就绪信号
        self.cache_ready.emit(target_index, state)
        
        build_time = (time.time() - build_start) * 1000
        if build_time > 100:
            print(f"[CacheWorker] 构建缓存到 {target_index}, 处理 {instructions_processed} 条指令, 耗时 {build_time:.1f}ms")
    
    def _save_checkpoint(self, index: int, state: RegisterState):
        """保存检查点"""
        with QMutexLocker(self._mutex):
            self.checkpoints[index] = state
            self._processed_checkpoints.add(index)
            
            # 保持索引列表有序
            if index not in self._checkpoint_indices:
                bisect.insort(self._checkpoint_indices, index)
        
        # 发送信号
        self.checkpoint_ready.emit(index, state)
        self.progress.emit(len(self.checkpoints), self.get_total_checkpoints_needed())


