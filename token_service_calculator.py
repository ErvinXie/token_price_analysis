#!/usr/bin/env python3
"""
LLM Token服务收益计算器
计算单服务收益、硬件并发能力，以及生命周期总收益
模型定价和服务性能解耦
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
import json
from database import TokenServiceDatabase, HardwareConfig, SLALevel


@dataclass
class ModelPricing:
    """模型定价配置"""
    model_name: str        # 模型名称
    input_price_per_m: float    # 输入token价格（元/M tokens）
    output_price_per_m: float   # 输出token价格（元/M tokens）

    def calculate_request_revenue(self, input_tokens: int, output_tokens: int) -> float:
        """计算单次请求的收益"""
        input_cost = (input_tokens / 1_000_000) * self.input_price_per_m
        output_cost = (output_tokens / 1_000_000) * self.output_price_per_m
        return input_cost + output_cost


@dataclass
class ServiceProfile:
    """单个服务的配置（服务质量）"""
    input_tokens: int      # 平均输入token数
    output_tokens: int     # 平均输出token数
    prefill_tps: float     # 服务prefill性能 (tokens/sec)
    decode_tps: float      # 服务decode性能 (tokens/sec)


@dataclass
class HardwarePerformance:
    """硬件性能配置 - 只关心并发能力"""
    hardware_name: str              # 硬件名称（关联数据库）
    max_concurrent_requests: int    # 最大并发请求数
    cost_mode: str = "rental"       # 成本模式: "rental" 或 "purchase"
    gpu_count: int = 1              # GPU数量
    power_consumption_w: int = 0    # 功耗（瓦特）


@dataclass
class ServiceParameters:
    """服务运行参数"""
    lifecycle_years: int          # 生命周期（年）
    average_load_factor: float    # 平均负载系数（0-1）
    uptime_percentage: float      # 可用性（0-1）
    sla_level: str = "standard"   # SLA等级


def load_model_prices_from_db() -> Dict[str, ModelPricing]:
    """从SQLite数据库加载模型价格"""
    db = TokenServiceDatabase()
    return db.get_model_pricing()


class TokenServiceCalculator:
    """Token服务收益计算器"""

    def __init__(self):
        self.model_pricing = None
        self.service_profile = None
        self.hardware = None
        self.service_params = None
        self.db = TokenServiceDatabase()  # 初始化数据库连接

    def set_model_pricing(self, model_pricing: ModelPricing):
        """设置模型定价"""
        self.model_pricing = model_pricing

    def set_model_from_catalog(self, model_key: str, category_filter: str = None):
        """从数据库中选择模型"""
        try:
            db = TokenServiceDatabase()
            if category_filter:
                # 按类别过滤
                models = db.get_models_by_category(category_filter)
                catalog = {model.model_key: model for model in models}
            else:
                catalog = db.get_model_pricing()
        except Exception as e:
            raise FileNotFoundError(f"无法加载价格数据: {e}\n请先运行: python migrate_data.py")

        if model_key not in catalog:
            available_models = list(catalog.keys())
            raise ValueError(f"模型 '{model_key}' 不存在，可用模型: {available_models[:10]}...")

        # 转换数据库ModelPricing到计算器ModelPricing
        db_model = catalog[model_key]
        self.model_pricing = ModelPricing(
            model_name=db_model.model_name,
            input_price_per_m=db_model.input_price_per_m,
            output_price_per_m=db_model.output_price_per_m
        )

    def list_available_models(self, category_filter: str = None) -> List[str]:
        """列出可用的模型"""
        try:
            db = TokenServiceDatabase()
            if category_filter:
                models = db.get_models_by_category(category_filter)
            else:
                catalog = db.get_model_pricing()
                models = list(catalog.values())
        except Exception as e:
            raise FileNotFoundError(f"无法加载价格数据: {e}\n请先运行: python migrate_data.py")

        # 返回模型key列表
        return [model.model_key for model in models]

    def set_service_profile(self, service_profile: ServiceProfile):
        self.service_profile = service_profile

    def set_hardware(self, hardware: HardwarePerformance):
        self.hardware = hardware

    def set_service_parameters(self, params: ServiceParameters):
        self.service_params = params

    def calculate_single_service_metrics(self) -> Dict:
        """计算单个服务的基础指标"""
        # 单次请求收益
        revenue_per_request = self.model_pricing.calculate_request_revenue(
            self.service_profile.input_tokens,
            self.service_profile.output_tokens
        )

        # 单次请求处理时间（基于服务质量参数）
        prefill_time = self.service_profile.input_tokens / self.service_profile.prefill_tps
        decode_time = self.service_profile.output_tokens / self.service_profile.decode_tps
        processing_time = prefill_time + decode_time

        # 理论QPS（每秒处理的请求数）
        qps_per_instance = 1 / processing_time if processing_time > 0 else 0

        # 每个实例每天处理的请求数
        daily_requests_per_instance = qps_per_instance * 3600 * 24 * self.service_params.uptime_percentage

        # 单实例日收益
        daily_revenue_per_instance = daily_requests_per_instance * revenue_per_request

        return {
            'revenue_per_request': revenue_per_request,
            'prefill_time': prefill_time,
            'decode_time': decode_time,
            'processing_time': processing_time,
            'qps_per_instance': qps_per_instance,
            'daily_requests_per_instance': daily_requests_per_instance,
            'daily_revenue_per_instance': daily_revenue_per_instance
        }

    def calculate_hardware_capacity(self) -> Dict:
        """计算硬件的总服务能力"""
        # 获取基于SLA的有效并发数
        effective_concurrent_requests = self.get_effective_concurrency()

        return {
            'max_concurrent_requests': effective_concurrent_requests,
            'instances_count': effective_concurrent_requests
        }

    def calculate_hardware_cost(self) -> Dict:
        """计算硬件成本（租用模式或购买模式）"""
        if not self.hardware:
            return {'monthly_cost': 0, 'lifecycle_cost': 0, 'cost_details': {}}

        # 从数据库获取硬件配置
        hardware_configs = {hw.name: hw for hw in self.db.get_hardware_configs()}

        if self.hardware.hardware_name not in hardware_configs:
            # 如果数据库中没有，使用默认计算
            if self.hardware.cost_mode == "rental":
                monthly_cost = 8000  # 默认租用成本
            else:
                # 购买模式：折旧 + 运营成本
                purchase_cost = 80000  # 默认购买成本
                depreciation_years = 5
                monthly_maintenance = 500
                monthly_power_cost = (self.hardware.power_consumption_w * 24 * 30) / 1000 * 0.8  # 假设电费0.8元/度
                monthly_cost = (purchase_cost / depreciation_years / 12) + monthly_maintenance + monthly_power_cost
        else:
            hw_config = hardware_configs[self.hardware.hardware_name]

            if self.hardware.cost_mode == "rental":
                monthly_cost = hw_config.monthly_rental_cost_yuan
            else:
                # 购买模式：折旧 + 运营成本
                monthly_depreciation = hw_config.purchase_cost_yuan / hw_config.depreciation_years / 12
                monthly_power_cost = (hw_config.power_consumption_w * 24 * 30) / 1000 * 0.8
                monthly_cost = monthly_depreciation + hw_config.monthly_maintenance_cost_yuan + monthly_power_cost

        lifecycle_cost = monthly_cost * 12 * self.service_params.lifecycle_years

        return {
            'monthly_cost': monthly_cost,
            'lifecycle_cost': lifecycle_cost,
            'cost_details': {
                'mode': self.hardware.cost_mode,
                'hardware_name': self.hardware.hardware_name,
                'gpu_count': self.hardware.gpu_count if hasattr(self.hardware, 'gpu_count') else 1
            }
        }

    def get_effective_concurrency(self) -> int:
        """获取基于SLA和服务质量的有效并发数"""
        if not all([self.model_pricing, self.hardware, self.service_params, self.service_profile]):
            return self.hardware.max_concurrent_requests if self.hardware else 0

        # 尝试从数据库获取精确的并发容量（基于input/output tokens）
        try:
            capacity = self.db.calculate_hardware_capacity(
                self.hardware.hardware_name,
                self._get_model_key_from_pricing(),
                self.service_params.sla_level,
                self.service_profile.input_tokens,
                self.service_profile.output_tokens
            )

            if capacity:
                return capacity['max_concurrent_requests']
        except Exception as e:
            print(f"⚠️  从数据库获取并发容量失败，使用简化计算: {e}")

        # 简化计算：基于SLA等级调整并发数
        sla_configs = {
            "basic": 1.0,
            "standard": 0.8,
            "premium": 0.6,
            "enterprise": 0.4
        }

        sla_ratio = sla_configs.get(self.service_params.sla_level, 0.8)
        return int(self.hardware.max_concurrent_requests * sla_ratio)

    def _get_model_key_from_pricing(self) -> str:
        """从模型定价获取模型key"""
        # 从model_pricing.model_name生成key
        import re
        model_name = self.model_pricing.model_name.lower()
        # 替换斜杠和其他字符
        key = re.sub(r'[^a-z0-9]+', '-', model_name)
        return key.strip('-')

    def calculate_lifecycle_revenue(self) -> Dict:
        """计算生命周期总收益"""
        # 单服务指标（包含基于硬件的处理时间）
        single_metrics = self.calculate_single_service_metrics()

        # 获取基于SLA的有效并发数
        effective_concurrent_requests = self.get_effective_concurrency()

        # 总QPS = 并发数 × 单个实例的QPS
        total_qps = effective_concurrent_requests * single_metrics['qps_per_instance']

        # 有效QPS（考虑负载系数）
        effective_qps = total_qps * self.service_params.average_load_factor

        # 每日总请求数
        daily_total_requests = effective_qps * 3600 * 24

        # 每日总收益
        daily_total_revenue = daily_total_requests * single_metrics['revenue_per_request']

        # 生命周期总收益
        days_in_year = 365
        total_days = self.service_params.lifecycle_years * days_in_year
        lifecycle_revenue = daily_total_revenue * total_days

        # 年化收益
        annual_revenue = daily_total_revenue * days_in_year

        # 硬件成本计算
        hardware_cost = self.calculate_hardware_cost()

        # 净收益（收益 - 成本）
        daily_net_revenue = daily_total_revenue - (hardware_cost['monthly_cost'] / 30)
        annual_net_revenue = annual_revenue - hardware_cost['monthly_cost'] * 12
        lifecycle_net_revenue = lifecycle_revenue - hardware_cost['lifecycle_cost']

        return {
            'single_request_revenue': single_metrics['revenue_per_request'],
            'prefill_time': single_metrics['prefill_time'],
            'decode_time': single_metrics['decode_time'],
            'processing_time': single_metrics['processing_time'],
            'qps_per_instance': single_metrics['qps_per_instance'],
            'effective_qps': effective_qps,
            'daily_total_requests': daily_total_requests,
            'daily_revenue': daily_total_revenue,
            'daily_net_revenue': daily_net_revenue,
            'annual_revenue': annual_revenue,
            'annual_net_revenue': annual_net_revenue,
            'lifecycle_revenue': lifecycle_revenue,
            'lifecycle_net_revenue': lifecycle_net_revenue,
            'concurrent_capacity': effective_concurrent_requests,
            'utilization_rate': self.service_params.average_load_factor,
            'hardware_cost': hardware_cost
        }

    def generate_report(self) -> str:
        """生成分析报告"""
        if not all([self.model_pricing, self.service_profile, self.hardware, self.service_params]):
            return "请设置所有必要的配置参数"

        metrics = self.calculate_lifecycle_revenue()

        return f"""
LLM Token服务收益分析报告
{'=' * 50}

服务质量配置:
- 输入Token数: {self.service_profile.input_tokens:,}
- 输出Token数: {self.service_profile.output_tokens:,}
- 输入输出比例: {self.service_profile.input_tokens/self.service_profile.output_tokens:.2f}
- Pre-fill TPS: {self.service_profile.prefill_tps:,.0f} tokens/sec
- Decode TPS: {self.service_profile.decode_tps:,.0f} tokens/sec

模型配置:
- 模型名称: {self.model_pricing.model_name}
- 输入Token: ¥{self.model_pricing.input_price_per_m:.2f}/M tokens
- 输出Token: ¥{self.model_pricing.output_price_per_m:.2f}/M tokens
- 单请求收益: ¥{metrics['single_request_revenue']:.6f}

硬件配置:
- 硬件类型: {self.hardware.hardware_name}
- GPU数量: {self.hardware.gpu_count}
- 成本模式: {self.hardware.cost_mode}
- 声明最大并发数: {self.hardware.max_concurrent_requests}

处理性能:
- Pre-fill时间: {metrics['prefill_time']:.4f} 秒
- Decode时间: {metrics['decode_time']:.4f} 秒
- 单次请求处理时间: {metrics['processing_time']:.4f} 秒
- 单实例QPS: {metrics['qps_per_instance']:.3f}

服务运行参数:
- 生命周期: {self.service_params.lifecycle_years} 年
- 平均负载系数: {self.service_params.average_load_factor:.1%}
- 服务可用性: {self.service_params.uptime_percentage:.1%}
- SLA等级: {self.service_params.sla_level}

成本分析:
- 硬件月成本: ¥{metrics['hardware_cost']['monthly_cost']:,.2f}
- 硬件总成本: ¥{metrics['hardware_cost']['lifecycle_cost']:,.2f}

收益分析:
- 有效并发容量: {metrics['concurrent_capacity']} 个请求
- 总QPS: {metrics['effective_qps']:.1f}
- 日处理请求量: {metrics['daily_total_requests']:,.0f}
- 日收益: ¥{metrics['daily_revenue']:,.2f}
- 日净收益: ¥{metrics['daily_net_revenue']:,.2f}
- 年收益: ¥{metrics['annual_revenue']:,.2f}
- 年净收益: ¥{metrics['annual_net_revenue']:,.2f}
- {self.service_params.lifecycle_years}年总收益: ¥{metrics['lifecycle_revenue']:,.2f}
- {self.service_params.lifecycle_years}年净收益: ¥{metrics['lifecycle_net_revenue']:,.2f}

利用率分析:
- 硬件利用率: {metrics['utilization_rate']:.1%}
- 理论峰值QPS: {metrics['effective_qps'] / metrics['utilization_rate']:.1f}
- 利润率: {(metrics['lifecycle_net_revenue'] / metrics['lifecycle_revenue'] * 100):.1f}%
"""


def create_example_calculator(model_key: str = "qwen2-7b") -> TokenServiceCalculator:
    """创建示例计算器"""
    calc = TokenServiceCalculator()

    # 设置模型定价
    calc.set_model_from_catalog(model_key)

    # 服务配置（服务质量）
    service_profile = ServiceProfile(
        input_tokens=8000,     # 8k输入tokens
        output_tokens=2000,    # 2k输出tokens
        prefill_tps=4000,     # 4k prefills/sec (RTX4090x4的理论值)
        decode_tps=20         # 20 decodes/sec
    )
    calc.set_service_profile(service_profile)

    # 硬件性能（只关心并发能力，TPS属于服务质量）
    hardware = HardwarePerformance(
        hardware_name="8xH20",  # 使用数据库中的硬件配置
        max_concurrent_requests=32,  # 最大32并发
        cost_mode="rental",    # 租用模式
        gpu_count=8,          # 8个GPU
        power_consumption_w=1500  # 1500W功耗
    )
    calc.set_hardware(hardware)

    # 服务参数
    params = ServiceParameters(
        lifecycle_years=3,           # 3年生命周期
        average_load_factor=0.3,     # 30%平均负载
        uptime_percentage=0.95,      # 95%可用性
        sla_level="standard"         # 标准SLA等级
    )
    calc.set_service_parameters(params)

    return calc




if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "models":
        # 显示可用模型列表
        calc = TokenServiceCalculator()
        try:
            category = sys.argv[2] if len(sys.argv) > 2 else None
            models = calc.list_available_models(category_filter=category)
            print(f"📋 可用模型列表 ({len(models)} 个):")
            for model in models:
                print(f"  - {model}")
        except Exception as e:
            print(f"❌ 获取模型列表失败: {e}")

  
    else:
        # 运行示例分析
        try:
            calculator = create_example_calculator("moonshotai-kimi-k2-thinking")
            print(calculator.generate_report())

            print("\n" + "=" * 60)
            print("💡 使用提示:")
            print("  python token_service_calculator.py models [category]  # 显示可用模型")
            print("  python price_updater.py                              # 更新价格数据")

        except FileNotFoundError:
            print("❌ 未找到价格文件，请先运行: python price_updater.py")
        except ValueError as e:
            print(f"❌ 错误: {e}")