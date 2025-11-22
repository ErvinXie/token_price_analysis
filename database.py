#!/usr/bin/env python3
"""
SQLite数据库管理模块
用于管理硬件配置、模型性能、成本计算等数据
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import os


@dataclass
class HardwareConfig:
    """硬件配置数据结构"""
    name: str
    gpu_type: str
    gpu_count: int
    gpu_memory_gb: int
    cpu_cores: int
    memory_gb: int
    storage_gb: int
    prefill_tps: int
    decode_tps: int
    max_concurrent_requests: int
    purchase_cost_yuan: float = 0.0
    monthly_rental_cost_yuan: float = 0.0
    power_consumption_w: int = 0
    monthly_maintenance_cost_yuan: float = 0.0
    depreciation_years: int = 5  # 折旧年限


@dataclass
class ModelHardwarePerformance:
    """模型在特定硬件上的性能数据"""
    model_key: str
    hardware_name: str
    prefill_tps: float
    decode_tps: float
    max_concurrent: int
    memory_usage_gb: float
    input_tokens_per_second: float
    output_tokens_per_second: float
    avg_response_time_ms: float


@dataclass
class ModelPricing:
    """模型定价数据结构"""
    model_key: str              # 模型唯一标识
    model_name: str             # 模型显示名称
    category: str               # 类别: free, paid, fine_tune
    input_price_per_m: float    # 输入价格（元/M tokens）
    output_price_per_m: float   # 输出价格（元/M tokens）
    description: str = ""       # 描述信息
    provider: str = ""          # 提供商
    parameter_size: str = ""    # 参数量
    model_type: str = ""        # 模型类型
    last_updated: str = ""      # 最后更新时间


@dataclass
class SLALevel:
    """服务水平等级定义"""
    level: str
    name: str
    description: str
    response_time_sla_ms: float
    availability_target: float
    max_concurrent_ratio: float  # 相对于硬件最大并发的比例


class TokenServiceDatabase:
    """Token服务数据库管理器"""

    def __init__(self, db_path: str = "token_service.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """初始化数据库表结构"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 模型定价表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_pricing (
                    model_key TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    category TEXT NOT NULL CHECK (category IN ('free', 'paid', 'fine_tune')),
                    input_price_per_m REAL NOT NULL DEFAULT 0.0,
                    output_price_per_m REAL NOT NULL DEFAULT 0.0,
                    description TEXT,
                    provider TEXT,
                    parameter_size TEXT,
                    model_type TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 模型定价历史表（用于追踪价格变化）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_pricing_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_key TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    input_price_per_m REAL NOT NULL,
                    output_price_per_m REAL NOT NULL,
                    description TEXT,
                    provider TEXT,
                    parameter_size TEXT,
                    model_type TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (model_key) REFERENCES model_pricing(model_key)
                )
            """)

            # 硬件配置表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hardware_configs (
                    name TEXT PRIMARY KEY,
                    gpu_type TEXT NOT NULL,
                    gpu_count INTEGER NOT NULL,
                    gpu_memory_gb INTEGER NOT NULL,
                    cpu_cores INTEGER NOT NULL,
                    memory_gb INTEGER NOT NULL,
                    storage_gb INTEGER NOT NULL,
                    prefill_tps INTEGER NOT NULL,
                    decode_tps INTEGER NOT NULL,
                    max_concurrent_requests INTEGER NOT NULL,
                    purchase_cost_yuan REAL DEFAULT 0.0,
                    monthly_rental_cost_yuan REAL DEFAULT 0.0,
                    power_consumption_w INTEGER DEFAULT 0,
                    monthly_maintenance_cost_yuan REAL DEFAULT 0.0,
                    depreciation_years INTEGER DEFAULT 5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 模型硬件性能表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_hardware_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_key TEXT NOT NULL,
                    hardware_name TEXT NOT NULL,
                    prefill_tps REAL NOT NULL,
                    decode_tps REAL NOT NULL,
                    max_concurrent INTEGER NOT NULL,
                    memory_usage_gb REAL NOT NULL,
                    input_tokens_per_second REAL NOT NULL,
                    output_tokens_per_second REAL NOT NULL,
                    avg_response_time_ms REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(model_key, hardware_name),
                    FOREIGN KEY (hardware_name) REFERENCES hardware_configs(name)
                )
            """)

            # SLA等级表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sla_levels (
                    level TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    response_time_sla_ms REAL NOT NULL,
                    availability_target REAL NOT NULL,
                    max_concurrent_ratio REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 硬件-模型-SLA并发容量表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hardware_model_sla_capacity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hardware_name TEXT NOT NULL,
                    model_key TEXT NOT NULL,
                    sla_level TEXT NOT NULL,
                    max_concurrent_requests INTEGER NOT NULL,
                    effective_qps REAL NOT NULL,
                    memory_usage_percent REAL DEFAULT 0.0,
                    cpu_usage_percent REAL DEFAULT 0.0,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(hardware_name, model_key, sla_level),
                    FOREIGN KEY (hardware_name) REFERENCES hardware_configs(name),
                    FOREIGN KEY (sla_level) REFERENCES sla_levels(level)
                )
            """)

            conn.commit()

    def add_hardware_config(self, hardware: HardwareConfig):
        """添加硬件配置"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO hardware_configs
                (name, gpu_type, gpu_count, gpu_memory_gb, cpu_cores, memory_gb, storage_gb,
                 prefill_tps, decode_tps, max_concurrent_requests,
                 purchase_cost_yuan, monthly_rental_cost_yuan, power_consumption_w,
                 monthly_maintenance_cost_yuan, depreciation_years, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hardware.name, hardware.gpu_type, hardware.gpu_count, hardware.gpu_memory_gb,
                hardware.cpu_cores, hardware.memory_gb, hardware.storage_gb,
                hardware.prefill_tps, hardware.decode_tps, hardware.max_concurrent_requests,
                hardware.purchase_cost_yuan, hardware.monthly_rental_cost_yuan,
                hardware.power_consumption_w, hardware.monthly_maintenance_cost_yuan,
                hardware.depreciation_years, datetime.now()
            ))
            conn.commit()

    def add_model_hardware_performance(self, performance: ModelHardwarePerformance):
        """添加模型硬件性能数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO model_hardware_performance
                (model_key, hardware_name, prefill_tps, decode_tps, max_concurrent,
                 memory_usage_gb, input_tokens_per_second, output_tokens_per_second,
                 avg_response_time_ms, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                performance.model_key, performance.hardware_name, performance.prefill_tps,
                performance.decode_tps, performance.max_concurrent, performance.memory_usage_gb,
                performance.input_tokens_per_second, performance.output_tokens_per_second,
                performance.avg_response_time_ms, datetime.now()
            ))
            conn.commit()

    def add_sla_level(self, sla: SLALevel):
        """添加SLA等级"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sla_levels
                (level, name, description, response_time_sla_ms,
                 availability_target, max_concurrent_ratio)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (sla.level, sla.name, sla.description, sla.response_time_sla_ms,
                  sla.availability_target, sla.max_concurrent_ratio))
            conn.commit()

    def calculate_hardware_capacity(self, hardware_name: str, model_key: str, sla_level: str) -> Optional[Dict]:
        """计算特定硬件-模型-SLA组合的并发容量"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 检查是否已有缓存数据
            cursor.execute("""
                SELECT max_concurrent_requests, effective_qps, memory_usage_percent, cpu_usage_percent
                FROM hardware_model_sla_capacity
                WHERE hardware_name = ? AND model_key = ? AND sla_level = ?
            """, (hardware_name, model_key, sla_level))

            cached = cursor.fetchone()
            if cached:
                return {
                    'max_concurrent_requests': cached[0],
                    'effective_qps': cached[1],
                    'memory_usage_percent': cached[2],
                    'cpu_usage_percent': cached[3]
                }

            # 计算容量并缓存
            capacity = self._calculate_new_capacity(hardware_name, model_key, sla_level)
            if capacity:
                self._cache_capacity(hardware_name, model_key, sla_level, capacity)

            return capacity

    def _calculate_new_capacity(self, hardware_name: str, model_key: str, sla_level: str) -> Optional[Dict]:
        """计算新的并发容量"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 获取模型硬件性能
            cursor.execute("""
                SELECT prefill_tps, decode_tps, max_concurrent, avg_response_time_ms
                FROM model_hardware_performance
                WHERE hardware_name = ? AND model_key = ?
            """, (hardware_name, model_key))

            perf = cursor.fetchone()
            if not perf:
                return None

            # 获取SLA要求
            cursor.execute("""
                SELECT response_time_sla_ms, max_concurrent_ratio, availability_target
                FROM sla_levels
                WHERE level = ?
            """, (sla_level,))

            sla = cursor.fetchone()
            if not sla:
                return None

            prefill_tps, decode_tps, max_concurrent, avg_response_time = perf
            response_time_sla, concurrent_ratio, availability = sla

            # 计算SLA限制下的并发数
            sla_limited_concurrent = int(max_concurrent * concurrent_ratio)

            # 计算有效QPS（考虑响应时间限制）
            if avg_response_time > response_time_sla:
                # 如果平均响应时间超过SLA，需要降低并发
                effective_concurrent = int(max_concurrent * (response_time_sla / avg_response_time))
            else:
                effective_concurrent = sla_limited_concurrent

            # 计算有效QPS
            effective_qps = effective_concurrent / (avg_response_time / 1000)

            return {
                'max_concurrent_requests': effective_concurrent,
                'effective_qps': effective_qps,
                'memory_usage_percent': (effective_concurrent / max_concurrent) * 100,
                'cpu_usage_percent': min(95, (effective_concurrent / max_concurrent) * 100)
            }

    def _cache_capacity(self, hardware_name: str, model_key: str, sla_level: str, capacity: Dict):
        """缓存计算结果"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO hardware_model_sla_capacity
                (hardware_name, model_key, sla_level, max_concurrent_requests,
                 effective_qps, memory_usage_percent, cpu_usage_percent, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (hardware_name, model_key, sla_level, capacity['max_concurrent_requests'],
                  capacity['effective_qps'], capacity['memory_usage_percent'],
                  capacity['cpu_usage_percent'], datetime.now()))
            conn.commit()

    def get_hardware_configs(self) -> List[HardwareConfig]:
        """获取所有硬件配置"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name, gpu_type, gpu_count, gpu_memory_gb, cpu_cores, memory_gb, storage_gb,
                       prefill_tps, decode_tps, max_concurrent_requests,
                       purchase_cost_yuan, monthly_rental_cost_yuan, power_consumption_w,
                       monthly_maintenance_cost_yuan, depreciation_years
                FROM hardware_configs
            """)

            return [HardwareConfig(*row) for row in cursor.fetchall()]

    def get_sla_levels(self) -> List[SLALevel]:
        """获取所有SLA等级"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT level, name, description, response_time_sla_ms,
                       availability_target, max_concurrent_ratio
                FROM sla_levels
            """)

            return [SLALevel(*row) for row in cursor.fetchall()]

    def add_model_pricing(self, pricing: ModelPricing):
        """添加模型定价"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 保存当前价格到历史表
            cursor.execute("""
                SELECT model_key, model_name, category, input_price_per_m, output_price_per_m,
                       description, provider, parameter_size, model_type
                FROM model_pricing WHERE model_key = ?
            """, (pricing.model_key,))

            existing = cursor.fetchone()
            if existing:
                # 将旧价格保存到历史表
                cursor.execute("""
                    INSERT INTO model_pricing_history
                    (model_key, model_name, category, input_price_per_m, output_price_per_m,
                     description, provider, parameter_size, model_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, existing + (datetime.now(),))

            # 更新或插入当前价格
            cursor.execute("""
                INSERT OR REPLACE INTO model_pricing
                (model_key, model_name, category, input_price_per_m, output_price_per_m,
                 description, provider, parameter_size, model_type, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (pricing.model_key, pricing.model_name, pricing.category,
                  pricing.input_price_per_m, pricing.output_price_per_m,
                  pricing.description, pricing.provider, pricing.parameter_size,
                  pricing.model_type, datetime.now()))
            conn.commit()

    def get_model_pricing(self, model_key: str = None) -> Dict[str, ModelPricing]:
        """获取模型定价数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if model_key:
                cursor.execute("""
                    SELECT model_key, model_name, category, input_price_per_m, output_price_per_m,
                           description, provider, parameter_size, model_type, last_updated
                    FROM model_pricing WHERE model_key = ?
                """, (model_key,))
            else:
                cursor.execute("""
                    SELECT model_key, model_name, category, input_price_per_m, output_price_per_m,
                           description, provider, parameter_size, model_type, last_updated
                    FROM model_pricing
                """)

            results = cursor.fetchall()
            return {row[0]: ModelPricing(*row) for row in results}

    def get_models_by_category(self, category: str) -> List[ModelPricing]:
        """按类别获取模型"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT model_key, model_name, category, input_price_per_m, output_price_per_m,
                       description, provider, parameter_size, model_type, last_updated
                FROM model_pricing WHERE category = ?
                ORDER BY model_name
            """, (category,))

            return [ModelPricing(*row) for row in cursor.fetchall()]

    def get_pricing_statistics(self) -> Dict:
        """获取定价统计信息"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 总体统计
            cursor.execute("SELECT COUNT(*) FROM model_pricing")
            total_models = cursor.fetchone()[0]

            cursor.execute("SELECT category, COUNT(*) FROM model_pricing GROUP BY category")
            category_stats = dict(cursor.fetchall())

            cursor.execute("""
                SELECT AVG(input_price_per_m), AVG(output_price_per_m)
                FROM model_pricing
                WHERE category = 'paid' AND input_price_per_m > 0
            """)
            avg_prices = cursor.fetchone()

            cursor.execute("""
                SELECT MIN(input_price_per_m), MAX(input_price_per_m)
                FROM model_pricing
                WHERE category = 'paid' AND input_price_per_m > 0
            """)
            price_range = cursor.fetchone()

            return {
                'total_models': total_models,
                'category_stats': category_stats,
                'avg_input_price': avg_prices[0] or 0,
                'avg_output_price': avg_prices[1] or 0,
                'min_price': price_range[0] or 0,
                'max_price': price_range[1] or 0,
                'last_updated': datetime.now().isoformat()
            }

    def migrate_json_to_sqlite(self, json_file: str = "model_prices/current_prices.json"):
        """从JSON文件迁移数据到SQLite"""
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            print(f"📦 开始迁移 {len(data['models'])} 个模型的价格数据...")

            migrated_count = 0
            for model_key, model_data in data['models'].items():
                # 解析模型名称以提取更多信息
                model_name = model_data['name']
                description = model_data.get('description', '')

                # 提取提供商信息
                provider = ""
                if '/' in model_name:
                    provider = model_name.split('/')[0]

                # 提取参数量信息
                parameter_size = ""
                import re
                size_match = re.search(r'(\d+[Bb])', description)
                if size_match:
                    parameter_size = size_match.group(1)

                # 确定模型类型
                model_type = ""
                if 'VL' in model_name:
                    model_type = "Vision-Language"
                elif 'Coder' in model_name:
                    model_type = "Code"
                elif 'Thinking' in model_name:
                    model_type = "Thinking"
                elif 'OCR' in model_name:
                    model_type = "OCR"
                else:
                    model_type = "Language"

                pricing = ModelPricing(
                    model_key=model_key,
                    model_name=model_name,
                    category=model_data['category'],
                    input_price_per_m=model_data['input_price_per_m'],
                    output_price_per_m=model_data['output_price_per_m'],
                    description=description,
                    provider=provider,
                    parameter_size=parameter_size,
                    model_type=model_type,
                    last_updated=model_data.get('last_updated', '')
                )

                self.add_model_pricing(pricing)
                migrated_count += 1

            print(f"✅ 成功迁移 {migrated_count} 个模型的价格数据到SQLite")
            return migrated_count

        except FileNotFoundError:
            print(f"❌ JSON文件不存在: {json_file}")
            return 0
        except Exception as e:
            print(f"❌ 迁移失败: {e}")
            return 0

    def init_default_data(self):
        """初始化默认数据"""
        # 默认SLA等级
        default_sla_levels = [
            SLALevel("basic", "基础服务", "标准响应时间，99%可用性", 2000, 0.99, 1.0),
            SLALevel("standard", "标准服务", "快速响应，99.5%可用性", 1000, 0.995, 0.8),
            SLALevel("premium", "高级服务", "极速响应，99.9%可用性", 500, 0.999, 0.6),
            SLALevel("enterprise", "企业服务", "超极速响应，99.99%可用性", 200, 0.9999, 0.4)
        ]

        for sla in default_sla_levels:
            self.add_sla_level(sla)

        # 默认硬件配置
        default_hardware = [
            HardwareConfig(
                name="RTX4090x4",
                gpu_type="RTX4090",
                gpu_count=4,
                gpu_memory_gb=24,
                cpu_cores=32,
                memory_gb=128,
                storage_gb=2000,
                prefill_tps=16000,
                decode_tps=400,
                max_concurrent_requests=200,
                purchase_cost_yuan=80000,
                monthly_rental_cost_yuan=8000,
                power_consumption_w=1500,
                monthly_maintenance_cost_yuan=500,
                depreciation_years=5
            ),
            HardwareConfig(
                name="A100x8",
                gpu_type="A100",
                gpu_count=8,
                gpu_memory_gb=80,
                cpu_cores=64,
                memory_gb=512,
                storage_gb=4000,
                prefill_tps=32000,
                decode_tps=800,
                max_concurrent_requests=400,
                purchase_cost_yuan=320000,
                monthly_rental_cost_yuan=32000,
                power_consumption_w=3000,
                monthly_maintenance_cost_yuan=2000,
                depreciation_years=5
            )
        ]

        for hardware in default_hardware:
            self.add_hardware_config(hardware)


def init_database():
    """初始化数据库和默认数据"""
    db = TokenServiceDatabase()
    db.init_default_data()
    print("✓ 数据库初始化完成")

    # 显示初始化的数据
    print(f"\n📋 硬件配置 ({len(db.get_hardware_configs())} 个):")
    for hw in db.get_hardware_configs():
        print(f"  - {hw.name}: {hw.gpu_type}x{hw.gpu_count}, 购买:¥{hw.purchase_cost_yuan:,}, 租用:¥{hw.monthly_rental_cost_yuan:,}/月")

    print(f"\n🎯 SLA等级 ({len(db.get_sla_levels())} 个):")
    for sla in db.get_sla_levels():
        print(f"  - {sla.level}: {sla.name}, 响应时间:{sla.response_time_sla_ms}ms, 可用性:{sla.availability_target*100:.1f}%")


if __name__ == "__main__":
    init_database()