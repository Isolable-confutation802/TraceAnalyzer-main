"""
寄存器模型 - ARM64寄存器封装
"""


class Register:
    """ARM64寄存器（W和X本质是同一寄存器）"""
    
    def __init__(self, name: str, value: int = 0):
        """
        初始化寄存器
        name: 寄存器名（X0-X30, SP, FP, LR等）
        value: 64位整数值
        """
        self.name = name  # 标准名称（统一使用X系列或特殊寄存器名）
        self._value = value & 0xFFFFFFFFFFFFFFFF  # 64位值
    
    @property
    def value(self) -> int:
        """获取64位值"""
        return self._value
    
    @value.setter
    def value(self, val: int):
        """设置64位值"""
        self._value = val & 0xFFFFFFFFFFFFFFFF
    
    def get_x_value(self) -> str:
        """获取X寄存器值（64位十六进制字符串）"""
        return f'0x{self._value:x}'
    
    def get_w_value(self) -> str:
        """获取W寄存器值（低32位十六进制字符串）"""
        w_val = self._value & 0xFFFFFFFF
        return f'0x{w_val:x}'
    
    def set_from_string(self, value_str: str):
        """从字符串设置值"""
        if not value_str:
            return
        
        # 去除0x前缀
        if value_str.startswith('0x') or value_str.startswith('0X'):
            value_str = value_str[2:]
        
        try:
            self._value = int(value_str, 16) & 0xFFFFFFFFFFFFFFFF
        except ValueError:
            pass
    
    def update_x(self, value_str: str):
        """更新X寄存器（64位）"""
        self.set_from_string(value_str)
    
    def update_w(self, value_str: str):
        """更新W寄存器（只更新低32位）"""
        if not value_str:
            return
        
        # 去除0x前缀
        if value_str.startswith('0x') or value_str.startswith('0X'):
            value_str = value_str[2:]
        
        try:
            w_val = int(value_str, 16) & 0xFFFFFFFF
            # 保留高32位，更新低32位
            high_bits = self._value & 0xFFFFFFFF00000000
            self._value = high_bits | w_val
        except ValueError:
            pass
    
    @staticmethod
    def normalize_name(reg_name: str) -> str:
        """
        标准化寄存器名（W -> X）
        W0 -> X0
        X0 -> X0
        SP -> SP
        """
        if reg_name.startswith('W') and reg_name[1:].isdigit():
            return 'X' + reg_name[1:]
        return reg_name
    
    @staticmethod
    def is_w_register(reg_name: str) -> bool:
        """判断是否是W系列寄存器"""
        return reg_name.startswith('W') and reg_name[1:].isdigit()
    
    @staticmethod
    def is_x_register(reg_name: str) -> bool:
        """判断是否是X系列寄存器"""
        return reg_name.startswith('X') and reg_name[1:].isdigit()
    
    def __repr__(self):
        return f"Register({self.name}, {self.get_x_value()})"


class RegisterState:
    """寄存器状态管理"""
    
    def __init__(self):
        self.registers: dict[str, Register] = {}
    
    def update(self, reg_name: str, value_str: str):
        """
        更新寄存器值
        自动处理W/X关系
        """
        # 标准化名称（W -> X）
        normalized_name = Register.normalize_name(reg_name)
        
        # 获取或创建寄存器
        if normalized_name not in self.registers:
            self.registers[normalized_name] = Register(normalized_name)
        
        reg = self.registers[normalized_name]
        
        # 根据原始名称决定更新方式
        if Register.is_w_register(reg_name):
            reg.update_w(value_str)
        else:
            reg.update_x(value_str)
    
    def get_register(self, reg_name: str) -> Register:
        """获取寄存器对象"""
        normalized_name = Register.normalize_name(reg_name)
        if normalized_name not in self.registers:
            self.registers[normalized_name] = Register(normalized_name)
        return self.registers[normalized_name]
    
    def get_x_value(self, reg_name: str) -> str:
        """获取X值"""
        return self.get_register(reg_name).get_x_value()
    
    def get_w_value(self, reg_name: str) -> str:
        """获取W值"""
        return self.get_register(reg_name).get_w_value()
    
    def get_all_registers(self) -> list[str]:
        """获取所有寄存器名称"""
        return sorted(self.registers.keys())
    
    def copy(self) -> 'RegisterState':
        """复制状态"""
        new_state = RegisterState()
        for name, reg in self.registers.items():
            new_state.registers[name] = Register(name, reg.value)
        return new_state
    
    def __repr__(self):
        return f"RegisterState({len(self.registers)} registers)"
