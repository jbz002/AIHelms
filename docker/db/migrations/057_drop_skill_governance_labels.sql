-- 移除 S4 治理 Label 体系（recommended/official/verified 治理徽标）。
-- 版本别名 Tag（skill_tags）保留不动。
-- 幂等：表/权限不存在时 DROP IF EXISTS 不报错。

DROP TABLE IF EXISTS aihelms.skill_labels;
DROP TABLE IF EXISTS aihelms.label_definitions;

DELETE FROM aihelms.permissions WHERE code = 'skill:label:manage';
