from pathlib import Path

path = Path("src/echoes/final_discovery/m7_adapter.py")
text = path.read_text(encoding="utf-8")

replacements = (
    (
        "            connection.execute(f\"SET temp_directory='{escaped_temp}'\")\n"
        "            pair_summary = connection.execute(\n",
        "            connection.execute(f\"SET temp_directory='{escaped_temp}'\")\n"
        "            connection.create_function(\n"
        "                \"final_discovery_candidate_pair_id\",\n"
        "                candidate_pair_id,\n"
        "            )\n"
        "            pair_summary = connection.execute(\n",
    ),
    (
        "                    ORDER BY p.candidate_pair_id\n",
        "                    ORDER BY final_discovery_candidate_pair_id(\n"
        "                        p.passage_a_id,\n"
        "                        p.passage_b_id\n"
        "                    )\n",
    ),
    (
        "    previous_source_candidate_id: str | None = None\n"
        "    for batch in parquet.iter_batches(batch_size=batch_size):\n"
        "        for row in batch.to_pylist():\n"
        "            values = cast(dict[str, object], row)\n"
        "            source_candidate_id = str(values[\"candidate_pair_id\"])\n"
        "            if not source_candidate_id or (\n"
        "                previous_source_candidate_id is not None\n"
        "                and source_candidate_id <= previous_source_candidate_id\n"
        "            ):\n"
        "                raise M7AdapterError(\"M7 projection candidate IDs are not unique and ordered\")\n"
        "            previous_source_candidate_id = source_candidate_id\n",
        "    previous_final_candidate_id: str | None = None\n"
        "    for batch in parquet.iter_batches(batch_size=batch_size):\n"
        "        for row in batch.to_pylist():\n"
        "            values = cast(dict[str, object], row)\n"
        "            source_candidate_id = str(values[\"candidate_pair_id\"])\n"
        "            if not source_candidate_id:\n"
        "                raise M7AdapterError(\"M7 projection carries an empty source candidate ID\")\n"
        "            passage_a_id = str(values[\"passage_a_id\"])\n"
        "            passage_b_id = str(values[\"passage_b_id\"])\n"
        "            final_candidate_id = candidate_pair_id(passage_a_id, passage_b_id)\n"
        "            if (\n"
        "                previous_final_candidate_id is not None\n"
        "                and final_candidate_id <= previous_final_candidate_id\n"
        "            ):\n"
        "                raise M7AdapterError(\n"
        "                    \"M7 projection final candidate IDs are not unique and ordered\"\n"
        "                )\n"
        "            previous_final_candidate_id = final_candidate_id\n",
    ),
    (
        "                candidate_pair_id=candidate_pair_id(passage_a_id, passage_b_id),\n",
        "                candidate_pair_id=final_candidate_id,\n",
    ),
)

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one exact replacement target, found {count}")
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
