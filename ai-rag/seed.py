# 初始化脚本：把 data/ 目录下的样例文档写入向量知识库。
# 运行方式：python seed.py

from pathlib import Path

from app.rag_service import rag_service


def main():
    data_dir = Path(__file__).parent / "data"
    # 遍历所有 Markdown 样例文件，逐个写入知识库。
    for path in sorted(data_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        chunks = rag_service.add_text(content, metadata={"source": path.name})
        print(f"seeded {path.name}: {chunks} chunks")
    print(f"total chunks: {rag_service.knowledge_count()}")


if __name__ == "__main__":
    main()
