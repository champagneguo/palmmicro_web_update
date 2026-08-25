# encoding: utf-8
"""
QMT 策略同步脚本

将本目录（python/QMT/yinhe/）下的策略文件同步到 QMT 安装目录 python/ 下。
源码在仓库里保持 UTF-8，同步到 QMT 时自动转成 GBK（QMT 的 Python 文件要求 GBK 编码）。

用法：
    python sync_qmt.py            # 同步全部映射文件
    python sync_qmt.py --dry-run  # 只打印，不实际拷贝
"""
import os
import sys

# QMT 安装目录（策略文件存放处）
QMT_PY_DIR = r"D:\银河证券QMT实盘 - 交易终端-北京\python"

# 源目录 = 本脚本所在目录
SRC_DIR = os.path.dirname(os.path.abspath(__file__))

# 文件名映射：源文件名 -> QMT 目标文件名
# 注意：目标文件名的 .py 后缀必须保留，QMT 依据文件名识别策略。
FILE_MAP = {
    "yinhe_server.py": "YINHE_SERVER.py",
    "yinhe_server_update.py": "YINHE_SERVER_UPDATE.py",
    "yinhe_server_fix.py": "YINHE_SERVER_FIX.py",
}

# QMT 要求的编码（源文件为 UTF-8，同步时转成该编码）
QMT_ENCODING = "gbk"


def _to_qmt_bytes(text: str) -> bytes:
    """把 UTF-8 源码文本转成 GBK 字节，并把编码声明改成 gbk"""
    text = text.replace("# encoding: utf-8", "# encoding: gbk", 1)
    return text.encode(QMT_ENCODING)


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    if not os.path.isdir(QMT_PY_DIR):
        print(f"[错误] QMT 目录不存在: {QMT_PY_DIR}")
        return 1

    for src_name, dst_name in FILE_MAP.items():
        src = os.path.join(SRC_DIR, src_name)
        dst = os.path.join(QMT_PY_DIR, dst_name)
        if not os.path.isfile(src):
            print(f"[跳过] 源文件不存在: {src}")
            continue

        if dry_run:
            print(f"[预览] {src_name} -> {dst} (转 {QMT_ENCODING})")
        else:
            text = open(src, encoding="utf-8").read()
            data = _to_qmt_bytes(text)
            with open(dst, "wb") as f:
                f.write(data)
            print(f"[同步] {src_name} -> {dst} (已转 {QMT_ENCODING})")

    print("同步完成" if not dry_run else "预览完成（未实际拷贝）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
