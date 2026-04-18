from __future__ import annotations

from textwrap import dedent
from typing import Any, Dict

from .artifact_quality import validate_artifact_quality
from .contract_models import ArtifactKind, ExecutionStrategy, StepContract


class ContractCompileError(ValueError):
    pass


class ContractCompiler:
    def compile(self, contract: StepContract) -> Dict[str, Any]:
        strategy = contract.operator.execution_strategy
        operator_type = contract.operator.type

        if strategy == ExecutionStrategy.PRIMITIVE_ACTION:
            artifact = self._compile_primitive(contract)
        elif strategy == ExecutionStrategy.DETERMINISTIC_SCRIPT:
            if operator_type == "rank_collection_numeric_max":
                artifact = self._compile_numeric_ranking(contract)
            elif operator_type == "extract_repeated_records":
                artifact = self._compile_repeated_records(contract)
            else:
                raise ContractCompileError(f"unsupported deterministic operator: {operator_type}")
        elif strategy == ExecutionStrategy.RUNTIME_AI:
            artifact = self._compile_runtime_ai(contract)
        else:
            raise ContractCompileError(f"unsupported execution strategy: {strategy}")

        quality = validate_artifact_quality(contract, artifact)
        if not quality.passed:
            raise ContractCompileError(quality.message)
        return artifact

    @staticmethod
    def _base_artifact(contract: StepContract, kind: ArtifactKind) -> Dict[str, Any]:
        return {
            "id": contract.id,
            "kind": kind,
            "description": contract.description,
            "contract_id": contract.id,
            "input_refs": list(contract.inputs.refs),
            "validation": [dict(item) for item in contract.validation.must],
        }

    def _compile_primitive(self, contract: StepContract) -> Dict[str, Any]:
        artifact = self._base_artifact(contract, ArtifactKind.PRIMITIVE_ACTION)
        operator_type = contract.operator.type
        if operator_type == "navigate":
            if not contract.target.url_template:
                raise ContractCompileError("navigate contract requires target.url_template")
            artifact.update(
                {
                    "action": "goto",
                    "target_url_template": contract.target.url_template,
                }
            )
            return artifact
        if operator_type in {"click", "fill", "press", "extract_text"}:
            if not contract.target.locator:
                raise ContractCompileError(f"{operator_type} contract requires target.locator")
            artifact.update({"action": operator_type, "locator": contract.target.locator})
            return artifact
        raise ContractCompileError(f"unsupported primitive operator: {operator_type}")

    def _compile_numeric_ranking(self, contract: StepContract) -> Dict[str, Any]:
        rule = dict(contract.operator.selection_rule or {})
        collection_selector = rule.get("collection_selector")
        value_selector = rule.get("value_selector")
        link_selector = rule.get("link_selector")
        url_prefix = rule.get("url_prefix", "")
        result_key = contract.outputs.blackboard_key

        if not collection_selector or not value_selector or not link_selector:
            raise ContractCompileError(
                "rank_collection_numeric_max requires collection_selector, value_selector, and link_selector"
            )
        if not result_key:
            raise ContractCompileError("rank_collection_numeric_max requires outputs.blackboard_key")

        code = dedent(
            f"""
            import re

            async def run(page, board):
                collection_selector = {collection_selector!r}
                value_selector = {value_selector!r}
                link_selector = {link_selector!r}
                url_prefix = {url_prefix!r}
                rows = await page.locator(collection_selector).all()
                best = None
                best_value = None

                for row in rows:
                    try:
                        value_text = (await row.locator(value_selector).first.inner_text()).strip()
                        normalized = value_text.replace(",", "").strip().lower()
                        match = re.search(r"\\d+(?:\\.\\d+)?", normalized)
                        if not match:
                            continue
                        value = float(match.group(0))
                        if "k" in normalized:
                            value *= 1000
                        elif "m" in normalized:
                            value *= 1000000

                        link = row.locator(link_selector).first
                        href = await link.get_attribute("href")
                        title = (await link.inner_text()).strip()
                        if not href:
                            continue
                        url = href if href.startswith(("http://", "https://")) else f"{{url_prefix}}{{href}}"
                        if best_value is None or value > best_value:
                            best_value = value
                            best = {{"url": url, "title": title, "score": value}}
                    except Exception:
                        continue

                if best is None:
                    raise RuntimeError("No ranked collection item matched the contract")
                return best
            """
        ).strip()

        artifact = self._base_artifact(contract, ArtifactKind.DETERMINISTIC_SCRIPT)
        artifact.update({"code": code, "result_key": result_key, "pattern": "rank_collection_numeric_max"})
        return artifact

    def _compile_repeated_records(self, contract: StepContract) -> Dict[str, Any]:
        rule = dict(contract.operator.selection_rule or {})
        row_selector = rule.get("row_selector")
        fields = rule.get("fields")
        limit = int(rule.get("limit") or 50)
        result_key = contract.outputs.blackboard_key

        if not row_selector or not isinstance(fields, dict) or not fields:
            raise ContractCompileError("extract_repeated_records requires row_selector and fields")
        if not result_key:
            raise ContractCompileError("extract_repeated_records requires outputs.blackboard_key")

        code = dedent(
            f"""
            async def run(page, board):
                row_selector = {row_selector!r}
                fields = {fields!r}
                limit = {limit!r}
                rows = await page.locator(row_selector).all()
                records = []

                for row in rows[:limit]:
                    record = {{}}
                    for field_name, field_contract in fields.items():
                        selector = field_contract.get("selector")
                        attribute = field_contract.get("attribute")
                        if not selector:
                            record[field_name] = ""
                            continue
                        locator = row.locator(selector).first
                        if await locator.count() == 0:
                            record[field_name] = ""
                            continue
                        if attribute:
                            value = await locator.get_attribute(attribute)
                        else:
                            value = await locator.inner_text()
                        record[field_name] = (value or "").strip()
                    records.append(record)

                return records
            """
        ).strip()

        artifact = self._base_artifact(contract, ArtifactKind.DETERMINISTIC_SCRIPT)
        artifact.update({"code": code, "result_key": result_key, "pattern": "extract_repeated_records"})
        return artifact

    def _compile_runtime_ai(self, contract: StepContract) -> Dict[str, Any]:
        artifact = self._base_artifact(contract, ArtifactKind.RUNTIME_AI)
        artifact.update(
            {
                "prompt": contract.description or contract.intent.goal,
                "instruction_kind": contract.operator.type,
                "input_scope": {"mode": contract.target.type, "collection": contract.target.collection},
                "output_schema": contract.outputs.schema_value,
                "result_key": contract.outputs.blackboard_key,
                "allow_side_effect": contract.runtime_policy.allow_side_effect,
                "runtime_ai_reason": contract.runtime_policy.runtime_ai_reason,
            }
        )
        return artifact
