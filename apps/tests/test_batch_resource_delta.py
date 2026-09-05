"""批量资源增量更新：_merge_delta 合并语义 + BatchUpdateRequest 替换/增量互斥校验。"""

import pytest
from pydantic import ValidationError

from api.v1.ai_keys import BatchUpdateRequest
from services.ai_key_service import _merge_delta


class TestMergeDelta:
    def test_merge_delta_add_only_appends_without_duplicates(self):
        assert _merge_delta(["a", "b"], ["c"], None) == ["a", "b", "c"]
        assert _merge_delta(["a"], ["a", "b"], None) == ["a", "b"]

    def test_merge_delta_remove_only_filters(self):
        assert _merge_delta(["a", "b", "c"], None, ["b"]) == ["a", "c"]

    def test_merge_delta_remove_last_leaves_empty(self):
        assert _merge_delta(["a"], None, ["a"]) == []

    def test_merge_delta_add_and_remove_combined(self):
        assert _merge_delta(["a"], ["b"], ["a"]) == ["b"]

    def test_merge_delta_empty_current(self):
        assert _merge_delta([], ["x"], None) == ["x"]


class TestBatchUpdateRequestValidator:
    def test_replace_and_delta_conflict_rejected(self):
        with pytest.raises(ValidationError):
            BatchUpdateRequest(models=["a"], models_add=["b"])

    def test_delta_only_accepted(self):
        req = BatchUpdateRequest(models_add=["b"], models_remove=["c"])
        assert req.models_add == ["b"]
        assert req.models_remove == ["c"]

    def test_independent_resource_types_no_conflict(self):
        req = BatchUpdateRequest(models=["a"], mcps_add=[1])
        assert req.models == ["a"]
        assert req.mcps_add == [1]
