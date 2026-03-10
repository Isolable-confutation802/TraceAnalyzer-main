"""
指令视图控制器 - 虚拟滚动实现

核心原理：
1. 后台线程缓存所有行的数据（纯数据，不是UI组件）
2. 表格只保持固定行数（可见区域大小）
3. 使用自定义滚动条模拟160万行的滚动
4. 滚动时从数据缓存更新表格内容
"""
import math
from typing import Optional, Callable, List, Dict, TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QScrollBar, QLabel, QFrame, QHeaderView, QAbstractItemView, QApplication
)
from PySide6.QtCore import Qt, QTimer, QObject, Signal, QThread
from PySide6.QtGui import QColor, QFont, QWheelEvent, QKeySequence, QShortcut

if TYPE_CHECKING:
    from lazy_parser import LazyLogParser


class DataCacheWorker(QThread):
    """后台数据缓存线程 - 缓存所有行的数据到内存"""
    
    progress = Signal(int, int)  # current, total
    finished = Signal()
    
    def __init__(self, parser: 'LazyLogParser', instruction_count: int):
        super().__init__()
        self.parser = parser
        self.instruction_count = instruction_count
        self._running = True
        
        # 数据缓存列表
        self.data_cache: List[Dict] = [None] * instruction_count
    
    def run(self):
        """后台缓存所有数据"""
        print(f"[缓存] 开始缓存 {self.instruction_count} 行数据...")
        
        batch_size = 10000
        for start in range(0, self.instruction_count, batch_size):
            if not self._running:
                break
            
            end = min(start + batch_size, self.instruction_count)
            for i in range(start, end):
                if not self._running:
                    break
                instr_info = self.parser.get_instruction_info(i)
                if instr_info:
                    self.data_cache[i] = {
                        'num': str(i + 1),
                        'address': instr_info.address,
                        'offset': instr_info.offset,
                        'mnemonic': instr_info.mnemonic,
                        'operands': instr_info.operands,
                        'comment': instr_info.comment
                    }
            
            self.progress.emit(end, self.instruction_count)
        
        if self._running:
            self.finished.emit()
            print(f"[缓存] 数据缓存完成")
    
    def stop(self):
        self._running = False
    
    def get_row_data(self, index: int) -> Optional[Dict]:
        """获取指定行的数据"""
        if 0 <= index < len(self.data_cache):
            return self.data_cache[index]
        return None


class VirtualScrollTable(QWidget):
    """虚拟滚动表格
    
    核心特点：
    - 表格只有固定行数（可见区域）
    - 使用独立滚动条控制虚拟位置
    - 滚动时更新表格内容，不增删行
    """
    
    # 信号
    selection_changed = Signal(int)  # 逻辑行号
    row_clicked = Signal(int)  # 逻辑行号
    scroll_stopped = Signal(int)  # 当前可见的中间行
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.parser: Optional['LazyLogParser'] = None
        self.total_rows = 0  # 总行数（逻辑）
        self.visible_rows = 50  # 可见行数（动态计算）
        self.current_top = 0  # 当前顶部的逻辑行号
        self.selected_logical_row = -1  # 选中的逻辑行号
        
        # 数据缓存
        self.data_cache: Optional[DataCacheWorker] = None
        
        # 滚动状态
        self.is_scrolling = False
        self.allow_heavy_update = True
        self.scroll_timer = QTimer()
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(self._on_scroll_stopped)
        
        self._init_ui()
        
        # 初始化时计算可见行数
        QTimer.singleShot(0, self._calculate_visible_rows)
    
    def _init_ui(self):
        """初始化UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['#', '地址', '偏移', '指令', '操作数', '注释'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFont(QFont('Consolas', 10))
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 隐藏原生滚动条
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # 列宽
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 80)
        
        # 样式
        self.table.setStyleSheet("""
            QTableWidget::item:selected {
                background-color: rgb(37, 99, 235);
                color: white;
            }
        """)
        
        # 表格事件
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        
        # Ctrl+C 复制整行：在表格获得焦点时拦截，复制选中行的整行数据
        copy_row_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        copy_row_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        copy_row_shortcut.activated.connect(self._copy_selected_row_to_clipboard)
        
        layout.addWidget(self.table)
        
        # 虚拟滚动条
        self.scrollbar = QScrollBar(Qt.Vertical)
        self.scrollbar.setMinimum(0)
        self.scrollbar.valueChanged.connect(self._on_scrollbar_changed)
        layout.addWidget(self.scrollbar)
        
        # 初始化空表格（先使用默认值，稍后会动态计算）
        self._init_empty_table()
    
    def _calculate_visible_rows(self):
        """动态计算可见行数"""
        if not self.table:
            return
        
        # 获取表格视口的可用高度（viewport已经排除了表头）
        available_height = self.table.viewport().height()
        
        # 如果高度太小，直接返回
        if available_height <= 0:
            return
        
        # 获取行高（如果表格为空，使用默认行高）
        if self.table.rowCount() > 0:
            row_height = self.table.rowHeight(0)
        else:
            # 如果没有行，创建一个临时行来获取行高
            self.table.setRowCount(1)
            row_height = self.table.rowHeight(0)
            if row_height <= 0:
                # 如果还是0，设置一个默认行高并重新获取
                self.table.setRowHeight(0, 24)
                row_height = self.table.rowHeight(0)
            self.table.setRowCount(0)
        
        # 如果行高为0，使用默认值
        if row_height <= 0:
            row_height = 24  # 默认行高
        
        # 计算可见行数：使用向上取整，充分利用空间
        # 方法1：直接向上取整，充分利用所有可用空间
        # 方法2：添加一点余量（比如多算0.8行），确保能显示更多行
        # 这里使用方法2，因为实际显示时可能有一些边距等
        calculated_rows = (available_height + row_height * 0.8) / row_height
        new_visible_rows = max(1, int(math.ceil(calculated_rows)))
        
        # 调试输出（可选，用于验证计算）
        # print(f"[可见行计算] 可用高度: {available_height}, 行高: {row_height}, 计算行数: {calculated_rows:.2f}, 最终行数: {new_visible_rows}")
        
        # 如果可见行数发生变化，更新表格
        if new_visible_rows != self.visible_rows:
            # 保存当前状态
            old_selected = self.selected_logical_row
            old_top = self.current_top
            
            self.visible_rows = new_visible_rows
            
            # 更新表格行数
            current_row_count = self.table.rowCount()
            if current_row_count != self.visible_rows:
                # 调整表格行数
                if self.visible_rows > current_row_count:
                    # 需要增加行
                    for row in range(current_row_count, self.visible_rows):
                        for col in range(6):
                            item = QTableWidgetItem('')
                            self.table.setItem(row, col, item)
                else:
                    # 需要减少行（删除多余的行）
                    self.table.setRowCount(self.visible_rows)
            
            # 更新滚动条范围（如果有数据）
            if self.total_rows > 0:
                max_scroll = max(0, self.total_rows - self.visible_rows)
                self.scrollbar.setMaximum(max_scroll)
                self.scrollbar.setPageStep(self.visible_rows)
                
                # 如果当前滚动位置超出范围，调整
                if self.current_top > max_scroll:
                    self.current_top = max_scroll
                    self.scrollbar.setValue(self.current_top)
                
                # 更新可见行数据
                self._update_visible_rows()
                
                # 恢复选中状态
                if old_selected >= 0:
                    self.select_logical_row(old_selected)
    
    def resizeEvent(self, event):
        """窗口大小变化事件"""
        super().resizeEvent(event)
        # 延迟计算，等待布局完成
        QTimer.singleShot(10, self._calculate_visible_rows)
    
    def _init_empty_table(self):
        """初始化空表格行"""
        # 先使用默认值，实际会在 _calculate_visible_rows 中调整
        self.table.setRowCount(self.visible_rows)
        for row in range(self.visible_rows):
            for col in range(6):
                item = QTableWidgetItem('')
                self.table.setItem(row, col, item)
    
    def wheelEvent(self, event: QWheelEvent):
        """鼠标滚轮事件"""
        delta = event.angleDelta().y()
        steps = -delta // 40  # 每次滚动3行左右
        new_value = self.scrollbar.value() + steps
        new_value = max(0, min(new_value, self.scrollbar.maximum()))
        self.scrollbar.setValue(new_value)
        event.accept()
    
    def set_data(self, parser: 'LazyLogParser', total_rows: int):
        """设置数据源"""
        # 停止之前的缓存线程
        if self.data_cache:
            self.data_cache.stop()
            self.data_cache.wait()
        
        self.parser = parser
        self.total_rows = total_rows
        self.current_top = 0
        self.selected_logical_row = -1
        
        # 确保可见行数是最新的（窗口大小可能已变化）
        self._calculate_visible_rows()
        
        # 更新滚动条范围
        max_scroll = max(0, total_rows - self.visible_rows)
        self.scrollbar.setMaximum(max_scroll)
        self.scrollbar.setPageStep(self.visible_rows)
        self.scrollbar.setValue(0)
        
        # 启动后台数据缓存
        self.data_cache = DataCacheWorker(parser, total_rows)
        self.data_cache.progress.connect(self._on_cache_progress)
        self.data_cache.finished.connect(self._on_cache_finished)
        self.data_cache.start()
        
        # 立即显示前N行（直接从parser读取）
        self._update_visible_rows()
    
    def _on_cache_progress(self, current: int, total: int):
        """缓存进度"""
        pass  # 可以更新进度条
    
    def _on_cache_finished(self):
        """缓存完成"""
        print("[虚拟滚动] 数据缓存完成，滚动将更流畅")
    
    def _on_scrollbar_changed(self, value: int):
        """滚动条值改变"""
        self.current_top = value
        self.is_scrolling = True
        self.allow_heavy_update = False
        
        # 更新可见行
        self._update_visible_rows()
        
        # 重置滚动停止定时器
        self.scroll_timer.stop()
        self.scroll_timer.start(200)
    
    def _update_visible_rows(self):
        """更新可见区域的行数据"""
        self.table.setUpdatesEnabled(False)
        try:
            for visual_row in range(self.visible_rows):
                logical_row = self.current_top + visual_row
                self._update_row(visual_row, logical_row)
        finally:
            self.table.setUpdatesEnabled(True)
    
    def _update_row(self, visual_row: int, logical_row: int):
        """更新单行数据"""
        if logical_row >= self.total_rows:
            # 超出范围，清空
            for col in range(6):
                item = self.table.item(visual_row, col)
                if item:
                    item.setText('')
            return
        
        # 优先从缓存获取，否则直接从parser获取
        data = None
        if self.data_cache and self.data_cache.data_cache[logical_row]:
            data = self.data_cache.data_cache[logical_row]
        elif self.parser:
            instr_info = self.parser.get_instruction_info(logical_row)
            if instr_info:
                data = {
                    'num': str(logical_row + 1),
                    'address': instr_info.address,
                    'offset': instr_info.offset,
                    'mnemonic': instr_info.mnemonic,
                    'operands': instr_info.operands,
                    'comment': instr_info.comment
                }
        
        if not data:
            return
        
        # 更新单元格
        colors = [
            QColor(128, 128, 128),  # 序号
            QColor(86, 156, 214),   # 地址
            QColor(128, 128, 128),  # 偏移
            QColor(220, 220, 170),  # 指令
            QColor(206, 145, 120),  # 操作数
            QColor(106, 153, 85),   # 注释
        ]
        values = [data['num'], data['address'], data['offset'], 
                  data['mnemonic'], data['operands'], data['comment']]
        
        for col, (value, color) in enumerate(zip(values, colors)):
            item = self.table.item(visual_row, col)
            if item:
                item.setText(value)
                item.setForeground(color)
                if col == 0:
                    item.setTextAlignment(Qt.AlignCenter)
    
    def _on_scroll_stopped(self):
        """滚动停止"""
        self.is_scrolling = False
        self.allow_heavy_update = True
        
        # 发送滚动停止信号，带上当前中间行的逻辑行号
        middle_row = self.current_top + self.visible_rows // 2
        if middle_row >= self.total_rows:
            middle_row = self.total_rows - 1
        
        if self.selected_logical_row < 0:
            self.selected_logical_row = middle_row
        
        self.scroll_stopped.emit(self.selected_logical_row)
    
    def _on_table_selection_changed(self):
        """表格选中变化"""
        selected = self.table.selectedItems()
        if selected:
            visual_row = selected[0].row()
            logical_row = self.current_top + visual_row
            self.selected_logical_row = logical_row
            
            if self.allow_heavy_update:
                self.selection_changed.emit(logical_row)
    
    def _on_cell_clicked(self, visual_row: int, col: int):
        """单元格点击"""
        logical_row = self.current_top + visual_row
        self.selected_logical_row = logical_row
        self.is_scrolling = False
        self.allow_heavy_update = True
        self.row_clicked.emit(logical_row)
    
    def select_logical_row(self, logical_row: int):
        """选中指定的逻辑行"""
        if logical_row < 0 or logical_row >= self.total_rows:
            return
        
        self.selected_logical_row = logical_row
        
        # 确保该行可见
        if logical_row < self.current_top or logical_row >= self.current_top + self.visible_rows:
            # 需要滚动
            new_top = max(0, logical_row - self.visible_rows // 2)
            new_top = min(new_top, self.total_rows - self.visible_rows)
            self.scrollbar.setValue(new_top)
        
        # 选中表格行
        visual_row = logical_row - self.current_top
        if 0 <= visual_row < self.visible_rows:
            self.table.selectRow(visual_row)
    
    def get_selected_logical_row(self) -> int:
        """获取选中的逻辑行号"""
        return self.selected_logical_row
    
    # 复制整行时的列宽（对齐用，全部用空格保证注释列对齐）
    _COPY_COL_WIDTHS = (6, 14, 10, 8, 40)  # #, 地址, 偏移, 助记符宽, 指令+操作数总宽

    def _copy_selected_row_to_clipboard(self):
        """Ctrl+C 时复制选中行的整行数据到剪贴板（固定列宽对齐，注释列对齐）"""
        logical_row = self.selected_logical_row
        if logical_row < 0 or logical_row >= self.total_rows:
            return
        data = None
        if self.data_cache:
            data = self.data_cache.get_row_data(logical_row)
        if not data and self.parser:
            instr_info = self.parser.get_instruction_info(logical_row)
            if instr_info:
                data = {
                    'num': str(logical_row + 1),
                    'address': instr_info.address,
                    'offset': instr_info.offset,
                    'mnemonic': instr_info.mnemonic,
                    'operands': instr_info.operands,
                    'comment': instr_info.comment
                }
        if not data:
            return
        w_num, w_addr, w_offset, w_mnemonic, w_instr = self._COPY_COL_WIDTHS
        num_str = (data.get('num') or '').strip()[:w_num].ljust(w_num)
        addr_str = (data.get('address') or '').strip()[:w_addr].ljust(w_addr)
        offset_str = (data.get('offset') or '').strip()[:w_offset].ljust(w_offset)
        mnemonic = (data.get('mnemonic') or '').strip()[:w_mnemonic].ljust(w_mnemonic)
        operands = (data.get('operands') or '').strip()
        # 指令列只用空格、不用 Tab，保证「 ;注释」起始列对齐
        instr_part = (mnemonic + ' ' + operands).strip()[:w_instr].ljust(w_instr)
        comment = (data.get('comment') or '').strip()
        line = f"{num_str} {addr_str} {offset_str} {instr_part} ;{comment}"
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(line)
    
    def clear(self):
        """清空"""
        if self.data_cache:
            self.data_cache.stop()
            self.data_cache.wait()
            self.data_cache = None
        
        self.total_rows = 0
        self.current_top = 0
        self.selected_logical_row = -1
        self.scrollbar.setMaximum(0)
        
        for visual_row in range(self.visible_rows):
            for col in range(6):
                item = self.table.item(visual_row, col)
                if item:
                    item.setText('')


# 兼容旧接口的包装类
class InstructionViewController(QObject):
    """指令视图控制器 - 兼容旧接口"""
    
    scroll_stopped = Signal(int)
    request_precache = Signal(int, int)
    
    def __init__(self, table: QTableWidget, parent=None):
        super().__init__(parent)
        # 注意：这个table参数会被忽略，我们使用VirtualScrollTable
        self.virtual_table: Optional[VirtualScrollTable] = None
        self.parser = None
        self.instruction_count = 0
        self.is_scrolling = False
        self.allow_heavy_update = True
        self.selected_index = -1
    
    def set_virtual_table(self, virtual_table: VirtualScrollTable):
        """设置虚拟滚动表格"""
        self.virtual_table = virtual_table
        self.virtual_table.scroll_stopped.connect(self._on_scroll_stopped)
        self.virtual_table.selection_changed.connect(self._on_selection_changed)
        self.virtual_table.row_clicked.connect(self._on_row_clicked)
    
    def set_parser(self, parser: 'LazyLogParser', instruction_count: int):
        """设置解析器"""
        self.parser = parser
        self.instruction_count = instruction_count
        self.selected_index = -1
    
    def initialize_table(self, initial_batch_size: int = 500):
        """初始化表格"""
        if self.virtual_table and self.parser:
            self.virtual_table.set_data(self.parser, self.instruction_count)
    
    def _on_scroll_stopped(self, logical_row: int):
        """滚动停止"""
        self.is_scrolling = False
        self.allow_heavy_update = True
        self.selected_index = logical_row
        self.scroll_stopped.emit(logical_row)
    
    def _on_selection_changed(self, logical_row: int):
        """选中变化"""
        self.selected_index = logical_row
    
    def _on_row_clicked(self, logical_row: int):
        """行点击"""
        self.is_scrolling = False
        self.allow_heavy_update = True
        self.selected_index = logical_row
    
    def on_instruction_clicked(self):
        """点击指令"""
        self.is_scrolling = False
        self.allow_heavy_update = True
    
    def ensure_row_rendered(self, row: int):
        """确保行已渲染（虚拟滚动不需要）"""
        pass
    
    def select_row(self, row: int, scroll_to: bool = True):
        """选中行"""
        if self.virtual_table:
            self.virtual_table.select_logical_row(row)
    
    def clear(self):
        """清空"""
        if self.virtual_table:
            self.virtual_table.clear()
        self.selected_index = -1
