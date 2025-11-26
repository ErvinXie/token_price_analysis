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

            # 服务配置表（ServiceProfile）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS service_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    prefill_tps INTEGER NOT NULL,
                    decode_tps INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name)
                )
            """)

            # 服务配置-硬件容量关联表（MN关系）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS service_profile_hardware_capacity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_profile_id INTEGER NOT NULL,
                    hardware_name TEXT NOT NULL,
                    max_concurrent_requests INTEGER NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(service_profile_id, hardware_name),
                    FOREIGN KEY (service_profile_id) REFERENCES service_profiles(id),
                    FOREIGN KEY (hardware_name) REFERENCES hardware_configs(name)
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

    def add_service_profile(self, name: str, description: str, input_tokens: int,
                           output_tokens: int, prefill_tps: int, decode_tps: int) -> int:
        """添加服务配置，返回ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO service_profiles
                (name, description, input_tokens, output_tokens, prefill_tps, decode_tps, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, description, input_tokens, output_tokens, prefill_tps, decode_tps, datetime.now()))

            # 获取插入的ID
            cursor.execute("SELECT last_insert_rowid()")
            profile_id = cursor.fetchone()[0]
            conn.commit()
            return profile_id

    def get_service_profile(self, profile_id: int):
        """获取服务配置 by ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, description, input_tokens, output_tokens, prefill_tps, decode_tps
                FROM service_profiles
                WHERE id = ?
            """, (profile_id,))

            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "input_tokens": row[3],
                    "output_tokens": row[4],
                    "prefill_tps": row[5],
                    "decode_tps": row[6]
                }
            return None

    def add_service_profile_hardware_capacity(self, service_profile_id: int, hardware_name: str,
                                             max_concurrent_requests: int, notes: str = ""):
        """添加服务配置-硬件容量关联"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO service_profile_hardware_capacity
                (service_profile_id, hardware_name, max_concurrent_requests, notes, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (service_profile_id, hardware_name, max_concurrent_requests, notes, datetime.now()))
            conn.commit()

    def get_service_profile_hardware_capacity(self, service_profile_id: int, hardware_name: str) -> Optional[int]:
        """获取某个服务配置在某个硬件上的最大并发数"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT max_concurrent_requests
                FROM service_profile_hardware_capacity
                WHERE service_profile_id = ? AND hardware_name = ?
            """, (service_profile_id, hardware_name))

            result = cursor.fetchone()
            return result[0] if result else None

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
                     description, provider, parameter_size, model_type, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

        # 默认服务配置（服务质量配置）
        # 配置1: 聊天服务（8k输入, 2k输出）
        chat_service_id = self.add_service_profile(
            name="chat_service",
            description="聊天对话服务：8k输入, 2k输出",
            input_tokens=8000,
            output_tokens=2000,
            prefill_tps=16000,
            decode_tps=400
        )

        # 配置2: 文档摘要服务（32k输入, 4k输出）
        summary_service_id = self.add_service_profile(
            name="summary_service",
            description="文档摘要服务：32k输入, 4k输出",
            input_tokens=32000,
            output_tokens=4000,
            prefill_tps=16000,
            decode_tps=400
        )

        # 配置3: 代码生成服务（4k输入, 8k输出）
        code_service_id = self.add_service_profile(
            name="code_service",
            description="代码生成服务：4k输入, 8k输出",
            input_tokens=4000,
            output_tokens=8000,
            prefill_tps=16000,
            decode_tps=400
        )

        # 添加容量关联：RTX4090x4 支持的服务配置
        # 聊天服务在RTX4090x4上的容量
        self.add_service_profile_hardware_capacity(
            service_profile_id=chat_service_id,
            hardware_name="RTX4090x4",
            max_concurrent_requests=200,
            notes="8k/2k对话服务，实测200并发"
        )

        # 文档摘要在RTX4090x4上的容量（token多，并发更少）
        self.add_service_profile_hardware_capacity(
            service_profile_id=summary_service_id,
            hardware_name="RTX4090x4",
            max_concurrent_requests=80,
            notes="32k/4k长文本处理，受限于显存"
        )

        # 代码生成在RTX4090x4上的容量
        self.add_service_profile_hardware_capacity(
            service_profile_id=code_service_id,
            hardware_name="RTX4090x4",
            max_concurrent_requests=150,
            notes="4k/8k代码生成，解码压力大"
        )

        # 添加容量关联：A100x8 支持的服务配置
        # A100x8性能更强，支持更多并发
        self.add_service_profile_hardware_capacity(
            service_profile_id=chat_service_id,
            hardware_name="A100x8",
            max_concurrent_requests=400,
            notes="8k/2k对话服务，A100x8实测"
        )

        self.add_service_profile_hardware_capacity(
            service_profile_id=summary_service_id,
            hardware_name="A100x8",
            max_concurrent_requests=200,
            notes="32k/4k长文本处理，A100x8大显存优势"
        )

        self.add_service_profile_hardware_capacity(
            service_profile_id=code_service_id,
            hardware_name="A100x8",
            max_concurrent_requests=300,
            notes="4k/8k代码生成，A100解码性能更强"
        )


def init_database():
    """初始化数据库和默认数据"""
    db = TokenServiceDatabase()
    db.init_default_data()
    print("✓ 数据库初始化完成")

    # 显示初始化的数据
    print(f"\n📋 硬件配置 ({len(db.get_hardware_configs())} 个):")
    for hw in db.get_hardware_configs():
        print(f"  - {hw.name}: {hw.gpu_type}x{hw.gpu_count}, 购买:¥{hw.purchase_cost_yuan:,}, 租用:¥{hw.monthly_rental_cost_yuan:,}/月")


if __name__ == "__main__":
    init_database()