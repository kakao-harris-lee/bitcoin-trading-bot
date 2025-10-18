#!/usr/bin/env python3
"""
strategy_generator.py
전략 생성기 - 템플릿 기반 전략 코드 생성
"""

from pathlib import Path
from datetime import datetime

class StrategyGenerator:
    """전략 생성기"""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.templates_dir = self.project_root / "strategies" / "_templates"

    def generate_plan(self, version: str, strategy_name: str) -> str:
        """계획 문서 생성"""
        template_path = self.templates_dir / "plan_template.md"
        template = template_path.read_text()

        timestamp = datetime.now().strftime("%y%m%d_%H%M")
        filename = f"{timestamp}.{version}.{strategy_name}.plan.md"

        # TODO: 템플릿 변수 치환

        return filename

    def create_strategy_folder(self, version: str, strategy_name: str):
        """전략 폴더 생성"""
        folder_name = f"{version}_{strategy_name}"
        strategy_dir = self.project_root / "strategies" / folder_name
        strategy_dir.mkdir(parents=True, exist_ok=True)

        # 기본 파일 생성
        (strategy_dir / "claude.md").touch()
        (strategy_dir / "strategy.py").touch()
        (strategy_dir / "config.json").touch()
        (strategy_dir / "process.md").touch()

        return strategy_dir

if __name__ == "__main__":
    generator = StrategyGenerator()
    generator.create_strategy_folder("v01", "simple_rsi")
    print("✅ 전략 폴더 생성 완료")
