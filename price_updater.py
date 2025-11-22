#!/usr/bin/env python3
"""
硅基流动价格更新脚本
从siliconflow.cn抓取最新的模型价格并保存到本地
"""

import re
from datetime import datetime
from typing import Dict, List, Tuple
import requests
from bs4 import BeautifulSoup
from database import TokenServiceDatabase, ModelPricing


class SiliconFlowPriceUpdater:
    """硅基流动价格更新器"""

    def __init__(self):
        self.db = TokenServiceDatabase()

    def scrape_prices(self) -> Dict[str, ModelPricing]:
        """真正从网页抓取最新价格"""
        print("🔍 正在从 siliconflow.cn 抓取最新价格...")

        url = "https://siliconflow.cn/pricing"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            print(f"✓ 成功获取网页内容 (状态码: {response.status_code})")
        except requests.RequestException as e:
            print(f"❌ 网页请求失败: {e}")
            return {}

        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            scraped_prices = self._parse_pricing_page(soup)

            if not scraped_prices:
                print("❌ 未能从网页解析到价格数据")
                print("请检查网页结构是否发生变化")
                return {}

            # 添加时间戳
            current_time = datetime.now().isoformat()
            for price in scraped_prices.values():
                price.last_updated = current_time

            print(f"✓ 成功抓取 {len(scraped_prices)} 个模型的价格信息")
            return scraped_prices

        except Exception as e:
            print(f"❌ 解析网页失败: {e}")
            print("请检查网页结构是否发生变化")
            return {}

    def _parse_pricing_page(self, soup: BeautifulSoup) -> Dict[str, ModelPricing]:
        """解析价格页面"""
        prices = {}

        # 查找价格表格 - 尝试多种可能的选择器
        tables = soup.find_all('table')

        if not tables:
            # 如果没有找到表格，尝试查找其他包含价格的元素
            return self._parse_price_from_elements(soup)

        for table in tables:
            # 获取表格标题，确定模型类别
            table_title = self._get_table_title(table)

            # 解析表格行
            rows = table.find_all('tr')
            if len(rows) < 2:  # 至少需要标题行和一行数据
                continue

            headers = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]

            # 确定价格列的位置
            input_price_col = self._find_column_index(headers, ['输入价格', '输入', 'Input', 'input'])
            output_price_col = self._find_column_index(headers, ['输出价格', '输出', 'Output', 'output'])
            model_name_col = self._find_column_index(headers, ['模型名称', '模型', 'Model', 'name'])

            if model_name_col == -1:
                continue

            # 解析数据行
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) <= max(model_name_col, input_price_col, output_price_col):
                    continue

                model_name = cells[model_name_col].get_text(strip=True)

                # 转换模型名称为key
                model_key = self._normalize_model_name(model_name)
                if not model_key:
                    continue

                # 解析价格
                input_price = self._parse_price(cells[input_price_col].get_text(strip=True)) if input_price_col != -1 else 0.0
                output_price = self._parse_price(cells[output_price_col].get_text(strip=True)) if output_price_col != -1 else 0.0

                # 获取描述信息
                description = self._extract_description(cells, len(headers))

                # 确定模型类别
                category = self._determine_category(table_title, model_name, input_price, output_price)

                # 提取额外信息
                provider = model_name.split('/')[0] if '/' in model_name else ""
                parameter_size = description
                model_type = self._determine_model_type(model_name)

                prices[model_key] = ModelPricing(
                    model_key=model_key,
                    model_name=model_name,
                    category=category,
                    input_price_per_m=input_price,
                    output_price_per_m=output_price,
                    description=description,
                    provider=provider,
                    parameter_size=parameter_size,
                    model_type=model_type,
                    last_updated=datetime.now().isoformat()
                )

        return prices

    def _parse_price_from_elements(self, soup: BeautifulSoup) -> Dict[str, ModelPricing]:
        """从网页元素中解析真实的价格信息"""
        prices = {}

        print("开始解析价格信息...")

        # 基于simple_test.py的发现，网页使用HTML表格结构
        # 查找所有包含价格信息的div容器
        price_containers = soup.find_all('div', class_='h-[43px] px-[12px] flex items-center')
        print(f"找到 {len(price_containers)} 个价格容器")

        for container in price_containers:
            try:
                # 提取模型信息
                flex_elements = container.find_all('div', class_='flex-1')
                if len(flex_elements) >= 3:
                    # 第一个元素是模型链接
                    model_link = flex_elements[0].find('a')
                    if model_link:
                        model_name = model_link.get_text(strip=True)

                        # 第二个元素是输入价格，第三个元素是输出价格
                        input_price_text = flex_elements[1].get_text(strip=True)
                        output_price_text = flex_elements[2].get_text(strip=True)

                        # 解析价格
                        input_price = self._parse_price_text(input_price_text)
                        output_price = self._parse_price_text(output_price_text)

                        # 确定模型类别
                        if input_price == 0 and output_price == 0:
                            category = "free"
                        else:
                            category = "paid"

                        # 标准化模型名称
                        model_key = self._normalize_model_name(model_name)
                        if not model_key:
                            continue

                        # 提取描述信息
                        description = self._extract_model_description_from_model_name(model_name)

                        # 提取额外信息
                        provider = model_name.split('/')[0] if '/' in model_name else ""
                        parameter_size = self._extract_model_description_from_model_name(model_name)
                        model_type = self._determine_model_type(model_name)

                        prices[model_key] = ModelPricing(
                            model_key=model_key,
                            model_name=model_name,
                            category=category,
                            input_price_per_m=input_price,
                            output_price_per_m=output_price,
                            description=description,
                            provider=provider,
                            parameter_size=parameter_size,
                            model_type=model_type,
                            last_updated=datetime.now().isoformat()
                        )

                        print(f"  解析模型: {model_name} - 输入:¥{input_price} 输出:¥{output_price}")

            except Exception as e:
                # 忽略解析错误，继续处理下一个
                continue

        # 如果上面的方法没有找到足够的数据，尝试查找更宽泛的模式
        if len(prices) < 10:
            print("尝试备用解析方法...")

            # 查找所有包含模型名称和价格的div
            model_divs = soup.find_all('div', string=re.compile(r'[A-Za-z0-9\-_\/]+.*?(免费|¥\d+\.?\d*)'))
            print(f"备用方法找到 {len(model_divs)} 个模型条目")

            for i, div in enumerate(model_divs[:20]):  # 限制处理数量
                try:
                    parent = div.parent
                    if parent:
                        text = parent.get_text()
                        # 查找模型名称和价格模式
                        model_price_match = re.search(r'([A-Za-z0-9\-_\/]+)[^免费¥]*?(?:免费|¥(\d+\.?\d*))', text)
                        if model_price_match:
                            model_name = model_price_match.group(1)
                            price_str = model_price_match.group(2)

                            price = float(price_str) if price_str else 0.0
                            category = "free" if price == 0 else "paid"

                            model_key = self._normalize_model_name(model_name)
                            if model_key and model_key not in prices:
                                description = self._extract_model_description_from_model_name(model_name)

                                # 提取额外信息
                                provider = model_name.split('/')[0] if '/' in model_name else ""
                                parameter_size = description
                                model_type = self._determine_model_type(model_name)

                                prices[model_key] = ModelPricing(
                                    model_key=model_key,
                                    model_name=model_name,
                                    category=category,
                                    input_price_per_m=price,
                                    output_price_per_m=price,
                                    description=description,
                                    provider=provider,
                                    parameter_size=parameter_size,
                                    model_type=model_type,
                                    last_updated=datetime.now().isoformat()
                                )
                except Exception:
                    continue

        print(f"✓ 成功解析了 {len(prices)} 个模型的价格信息")
        return prices

    def _determine_model_type(self, model_name: str) -> str:
        """确定模型类型"""
        if 'VL' in model_name:
            return "Vision-Language"
        elif 'Coder' in model_name:
            return "Code"
        elif 'Thinking' in model_name:
            return "Thinking"
        elif 'OCR' in model_name:
            return "OCR"
        elif 'Chat' in model_name:
            return "Chat"
        elif 'Instruct' in model_name:
            return "Instruction"
        else:
            return "Language"

    def _extract_model_description_from_model_name(self, model_name: str) -> str:
        """从模型名称中提取描述信息"""
        # 提取参数量信息
        size_patterns = [
            r'(\d+[Bb])',
            r'(\d+A3B)',
            r'(\d+GB)'
        ]

        for pattern in size_patterns:
            match = re.search(pattern, model_name)
            if match:
                return match.group(1)

        # 提取其他特征
        if 'Instruct' in model_name:
            return '对话模型'
        elif 'Coder' in model_name:
            return '代码模型'
        elif 'OCR' in model_name:
            return 'OCR模型'
        elif 'Thinking' in model_name:
            return '思考模型'
        elif 'VL' in model_name:
            return '视觉语言模型'
        else:
            return '语言模型'

    def _extract_model_name_from_text(self, text: str) -> str:
        """从文本中提取模型名称"""
        model_name_patterns = [
            r'(Qwen[^\s\n]*\d+[^\s\n]*[^\s\n])',
            r'(Qwen/Qwen[^\s\n]+)',
            r'(DeepSeek[^\s\n]+)',
            r'(Llama[^\s\n]+)',
            r'(GLM[^\s\n]+)',
            r'(Claude[^\s\n]+)',
            r'(GPT[^\s\n]+)',
            r'(internlm/[^\s\n]+)',
            r'(THUDM/[^\s\n]+)',
            r'(tencent/[^\s\n]+)',
            r'(inclusionAI/[^\s\n]+)',
            r'(ascend-tribe/[^\s\n]+)'
        ]

        for pattern in model_name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _extract_prices_from_container_text(self, text: str) -> Tuple[float, float]:
        """从容器文本中提取输入和输出价格"""
        # 查找推理价格模式
        inference_pattern = r'推理\s*\(\s*元\s*/\s*M\s*tokens\s*\)\s*¥?\s*(\d+\.?\d*)'
        inference_match = re.search(inference_pattern, text, re.IGNORECASE)

        if inference_match:
            inference_price = float(inference_match.group(1))
            # 如果只找到推理价格，假设输入价格相同
            return inference_price, inference_price

        # 查找通用的输入输出价格模式
        input_output_pattern = r'输入\s*\(\s*元\s*/\s*M\s*tokens\s*\)\s*¥?\s*(\d+\.?\d*).*?输出\s*\(\s*元\s*/\s*M\s*tokens\s*\)\s*¥?\s*(\d+\.?\d*)'
        input_output_match = re.search(input_output_pattern, text, re.IGNORECASE | re.DOTALL)

        if input_output_match:
            input_price = float(input_output_match.group(1))
            output_price = float(input_output_match.group(2))
            return input_price, output_price

        # 查找单一价格模式
        single_price_pattern = r'¥?\s*(\d+\.?\d*)\s*元\s*/\s*M\s*tokens'
        single_matches = re.findall(single_price_pattern, text, re.IGNORECASE)
        if single_matches:
            # 如果只有一个价格，假设输入输出价格相同
            price = float(single_matches[0])
            return price, price

        return None

    def _extract_model_description(self, text: str) -> str:
        """提取模型描述信息"""
        # 查找参数量信息
        size_pattern = r'(\d+[Bb])'
        size_match = re.search(size_pattern, text)
        if size_match:
            return size_match.group(1)

        # 查找其他描述性信息
        desc_patterns = [
            r'(免费|Free)',
            r'(推理|Inference)',
            r'(训练|Training)',
            r'(Chat|聊天)',
            r'(Code|代码)'
        ]

        descriptions = []
        for pattern in desc_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            descriptions.extend(matches)

        return ', '.join(set(descriptions)) if descriptions else ""

    def _determine_model_category(self, text: str, price: float) -> str:
        """确定模型类别"""
        if '训练' in text:
            return "fine_tune"
        elif price == 0 or '免费' in text.lower() or 'free' in text.lower():
            return "free"
        else:
            return "paid"

    def _get_table_title(self, table) -> str:
        """获取表格标题"""
        # 查找表格前的标题元素
        prev_sibling = table.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if prev_sibling:
            return prev_sibling.get_text(strip=True)

        # 查找表格内的标题
        title_element = table.find(['caption', 'th'])
        if title_element:
            return title_element.get_text(strip=True)

        return ""

    def _find_column_index(self, headers: List[str], keywords: List[str]) -> int:
        """查找列索引"""
        for i, header in enumerate(headers):
            if any(keyword.lower() in header.lower() for keyword in keywords):
                return i
        return -1

    def _normalize_model_name(self, name: str) -> str:
        """标准化模型名称"""
        if not name or name.lower() in ['模型', 'model', '']:
            return ""

        # 移除特殊字符，转换为小写，用连字符连接
        normalized = re.sub(r'[^\w\u4e00-\u9fff]', '-', name.lower())
        normalized = re.sub(r'-+', '-', normalized).strip('-')

        return normalized

    def _parse_price(self, price_text: str) -> float:
        """解析价格文本"""
        if not price_text:
            return 0.0

        # 移除非数字字符（保留小数点）
        clean_price = re.sub(r'[^\d.]', '', price_text)

        if not clean_price:
            return 0.0

        try:
            return float(clean_price)
        except ValueError:
            return 0.0

    def _parse_price_text(self, price_text: str) -> float:
        """解析价格文本 - 兼容免费和付费价格"""
        if not price_text:
            return 0.0

        # 检查是否为免费
        if '免费' in price_text or 'free' in price_text.lower():
            return 0.0

        # 移除非数字字符（保留小数点）
        clean_price = re.sub(r'[^\d.]', '', price_text)

        if not clean_price:
            return 0.0

        try:
            return float(clean_price)
        except ValueError:
            return 0.0

    def _extract_description(self, cells: List, total_cols: int) -> str:
        """提取描述信息"""
        if len(cells) > 3:  # 假设第4列之后是描述
            return ' '.join(cell.get_text(strip=True) for cell in cells[3:total_cols])
        return ""

    def _determine_category(self, table_title: str, model_name: str, input_price: float, output_price: float) -> str:
        """确定模型类别"""
        title_lower = table_title.lower()
        name_lower = model_name.lower()

        if '免费' in title_lower or 'free' in title_lower or (input_price == 0 and output_price == 0):
            return "free"
        elif '微调' in title_lower or 'finetune' in title_lower or 'fine-tune' in name_lower:
            return "fine_tune"
        elif input_price > 0 or output_price > 0:
            return "paid"
        else:
            return "free"

    
    def save_current_prices(self, prices: Dict[str, ModelPricing]):
        """保存当前价格到SQLite数据库"""
        updated_count = 0
        for model_key, pricing in prices.items():
            try:
                self.db.add_model_pricing(pricing)
                updated_count += 1
            except Exception as e:
                print(f"⚠️ 保存模型 {model_key} 失败: {e}")

        print(f"✓ 已更新 {updated_count} 个模型的价格到SQLite数据库")

    
    def update_prices(self):
        """更新价格的主函数"""
        try:
            # 抓取最新价格
            prices = self.scrape_prices()

            # 保存当前价格
            self.save_current_prices(prices)

            # 历史记录已自动保存在数据库中（通过add_model_pricing方法）

            print(f"🎉 价格更新完成！共更新 {len(prices)} 个模型")

            # 显示价格统计
            self.show_price_summary(prices)

        except Exception as e:
            print(f"❌ 价格更新失败: {e}")

    def show_price_summary(self, prices: Dict[str, ModelPricing]):
        """显示价格摘要"""
        stats = self.db.get_pricing_statistics()

        print(f"\n📊 价格摘要:")
        print(f"  总模型数: {stats['total_models']} 个")
        for category, count in stats['category_stats'].items():
            print(f"  {category}模型: {count} 个")
        print(f"  平均输入价格: ¥{stats['avg_input_price']:.2f}/M tokens")
        print(f"  平均输出价格: ¥{stats['avg_output_price']:.2f}/M tokens")
        print(f"  价格范围: ¥{stats['min_price']:.2f} - ¥{stats['max_price']:.2f}/M tokens")

    def list_prices(self, category_filter: str = None):
        """列出价格信息"""
        try:
            if category_filter:
                models = self.db.get_models_by_category(category_filter)
                print(f"📋 {category_filter.upper()} 模型价格列表:")
            else:
                catalog = self.db.get_model_pricing()
                models = list(catalog.values())
                print("📋 所有模型价格列表:")

            print(f"{'模型名称':<30} {'类别':<8} {'输入价格':<12} {'输出价格':<12} {'提供商':<15}")
            print("-" * 90)

            for price in models:
                input_price = f"¥{price.input_price_per_m:.2f}" if price.input_price_per_m > 0 else "免费"
                output_price = f"¥{price.output_price_per_m:.2f}" if price.output_price_per_m > 0 else "免费"
                print(f"{price.model_name:<30} {price.category:<8} {input_price:<12} {output_price:<12} {price.provider:<15}")

        except Exception as e:
            print(f"❌ 未找到价格数据: {e}")
            print("请先运行: python price_updater.py")


def main():
    """主函数"""
    import sys

    updater = SiliconFlowPriceUpdater()

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        # 列出价格
        category = sys.argv[2] if len(sys.argv) > 2 else None
        updater.list_prices(category)
    else:
        # 更新价格
        updater.update_prices()


if __name__ == "__main__":
    main()