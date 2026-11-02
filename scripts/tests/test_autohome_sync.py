#!/usr/bin/env python3
from __future__ import annotations

import base64
import io
import sys
import tarfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_exact_trim_specs_autohome as ah  # noqa: E402


def matrix(*titles: str) -> bytes:
    ids = [str(60000 + i) for i in range(len(titles))]
    rows = [
        ["Feature", *ids],
        ["车型名称", *titles],
        ["能源类型", *(["汽油"] * len(titles))],
        ["长*宽*高(mm)", *(["4700*1900*1700"] * len(titles))],
        ["轴距(mm)", *(["2750"] * len(titles))],
        ["360度全景影像", *(["●"] * len(titles))],
        ["主动刹车/主动安全系统", *(["●"] * len(titles))],
        ["巡航系统", *(["全速自适应巡航"] * len(titles))],
        ["电动后备厢", *(["●"] * len(titles))],
        ["前排座椅加热", *(["●"] * len(titles))],
        ["前排座椅通风", *(["-"] * len(titles))],
        ["CarPlay", *(["●"] * len(titles))],
        ["车道偏离预警系统", *(["●"] * len(titles))],
        ["车道保持辅助系统", *(["●"] * len(titles))],
        ["车道居中保持", *(["●"] * len(titles))],
        ["并线辅助", *(["●"] * len(titles))],
        ["前方碰撞预警", *(["●"] * len(titles))],
        ["后驻车雷达", *(["●"] * len(titles))],
        ["前驻车雷达", *(["●"] * len(titles))],
        ["天窗类型", *(["可开启全景天窗"] * len(titles))],
        ["无钥匙进入功能", *(["●"] * len(titles))],
        ["无钥匙启动系统", *(["●"] * len(titles))],
        ["远程启动功能", *(["●"] * len(titles))],
        ["手机无线充电功能", *(["●"] * len(titles))],
        ["中控屏幕尺寸", *(["12.3英寸"] * len(titles))],
        ["车联网", *(["●"] * len(titles))],
        ["OTA升级", *(["●"] * len(titles))],
        ["自动头灯", *(["●"] * len(titles))],
        ["自适应远近光", *(["●"] * len(titles))],
        ["燃油标号", *(["92号"] * len(titles))],
    ]
    import csv
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue().encode("utf-8")


def test_unique_exact_match():
    data = matrix("测试车 2021款 1.5T 自动尊贵版", "测试车 2021款 1.5T 自动旗舰版")
    candidates = ah.parse_matrix_csv(data, "测试_测试车.csv", "main", 123)
    c, score, reason = ah.choose_exact("测试车 2021款 1.5T 自动尊贵版", "测试车", candidates)
    assert reason == ""
    assert c is not None and c.spec_id == 60000
    assert score == 1.0
    trim_id, trim = ah.build_autohome_trim(c, score)
    assert trim_id.startswith("trim_ah_")
    assert trim["features"]["parking_adas"]["surround_360"] is True
    assert trim["features"]["active_safety"]["aeb"] is True
    assert trim["data_quality"]["identity_source"] == "autohome_exact_trim"


def test_year_mismatch_rejected():
    data = matrix("测试车 2022款 1.5T 自动尊贵版")
    candidates = ah.parse_matrix_csv(data, "测试_测试车.csv", "main", 123)
    c, _, reason = ah.choose_exact("测试车 2021款 1.5T 自动尊贵版", "测试车", candidates)
    assert c is None
    assert reason == "model_year_not_found"


def test_ambiguous_match_rejected():
    data = matrix("测试车 2021款 1.5T 自动尊贵版A", "测试车 2021款 1.5T 自动尊贵版B")
    candidates = ah.parse_matrix_csv(data, "测试_测试车.csv", "main", 123)
    c, _, reason = ah.choose_exact("测试车 2021款 1.5T 自动尊贵版", "测试车", candidates)
    assert c is None
    assert reason == "ambiguous_exact_trim_match"


def test_vault_decoder():
    import zstandard as zstd
    csv_bytes = matrix("测试车 2021款 1.5T 自动尊贵版")
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tf:
        info = tarfile.TarInfo("data/测试_测试车.csv")
        info.size = len(csv_bytes)
        tf.addfile(info, io.BytesIO(csv_bytes))
    zst = zstd.ZstdCompressor().compress(tar_buffer.getvalue())
    packed = base64.b85encode(zlib.compress(zst))
    decoded = ah.AutoHomeSource.decode_vault(packed)
    with tarfile.open(fileobj=io.BytesIO(decoded), mode="r:*") as tf:
        assert "data/测试_测试车.csv" in tf.getnames()


if __name__ == "__main__":
    test_unique_exact_match()
    test_year_mismatch_rejected()
    test_ambiguous_match_rejected()
    test_vault_decoder()
    print("autohome exact-trim sync tests passed")
