---
name: find-pipelines-by-service
description: Find all pipelines that use a specific type of linked service (e.g. Snowflake, AzureBlobStorage). Cross-references pipelines, datasets, and linked services.
---
# Find Pipelines by Linked Service Type

Find all pipelines in an ADF instance that use a specific type of linked service, through both direct activity references and indirect dataset references.

## Workflow

### Step 1: Resolve Target

User provides domain + environment.

```
resolve_adf_target(domain, environment)
```

If the user does not specify both, ask for clarification.

### Step 2: List Everything (parallel)

Call all three tools together:

- `adf_linked_service_list()` — names + types
- `adf_pipeline_list()` — saves each pipeline as `pipelines/{name}.json`
- `adf_dataset_list()` — saves all datasets as `datasets.json`

### Step 3: Identify Target Linked Services

From the linked service list, identify which ones match the user's request (e.g. type = `Snowflake` or `SnowflakeV2`).

If unsure about version (e.g. type just says "Snowflake" but user asked specifically for v1 vs v2), call `adf_linked_service_get()` on a few to inspect the full definition and confirm.

Collect the **names** of all matching linked services into a target set.

### Step 4: Inspect Actual Data Structure

Before writing any `exec_python` script, read sample files to understand the exact JSON keys. `exec_python` has high overhead, so invest time here to get it right on the first run.

Read **all three** in parallel:

- `read_file("datasets.json")` — check what keys each dataset object uses (e.g. `name`, `linked_service`, `linked_service_name`, `properties.linkedServiceName`, etc.)
- `read_file("pipelines/<first_pipeline>.json")` — check activity structure, how linked services and datasets are referenced
- `read_file("pipelines/<second_pipeline>.json")` — pick a different pipeline to confirm the pattern is consistent

From these samples, note the **exact field names** for:

1. **Dataset → linked service mapping**: what key holds the dataset name, what key holds the linked service reference
2. **Pipeline activity → linked service (direct)**: what key on the activity holds a direct linked service reference
3. **Pipeline activity → dataset (indirect)**: what key on the activity holds dataset references (`dataset`, `inputs`, `outputs`, or nested under `typeProperties`)
4. **Reference name field**: whether it's `reference_name`, `referenceName`, or something else

### Step 5: Cross-Reference with exec_python

Using the **exact field names** observed in Step 4, write a Python script that:

1. Loads `datasets.json` — builds a `dataset_name → linked_service_name` lookup
2. Iterates all `pipelines/*.json` files
3. For each pipeline, walks all activities and checks **both paths**:
   - **Direct**: activity itself references a linked service at the activity level
   - **Indirect**: activity references a dataset, then looks up that dataset in the `dataset → linked_service` mapping
4. Both paths must be checked — direct alone will miss dataset-based references, indirect alone will miss activity-level references
5. Writes clear logs for each pipeline checked and each match found (for debugging)
6. Writes result to `results.json`: `{ "pipeline_name": ["ls_name1", "ls_name2"], ... }`

**Reference code example** — adapt field names based on what you observed in Step 4:

```python
import json, os, glob as g

# --- Config ---
session_dir = os.environ.get("SESSION_DIR", ".")
target_ls_names = {"snowflake_v1_ls", "snowflake_v2_prod"}  # from Step 3

# --- Load datasets ---
# IMPORTANT: Use the exact keys you saw in Step 4
with open(os.path.join(session_dir, "datasets.json")) as f:
    datasets = json.load(f)
ds_to_ls = {ds["name"]: ds["linked_service"] for ds in datasets}
print(f"Loaded {len(ds_to_ls)} datasets")

# --- Scan pipelines ---
results = {}
pipeline_files = g.glob(os.path.join(session_dir, "pipelines", "*.json"))

for pf in pipeline_files:
    with open(pf) as f:
        pipeline = json.load(f)

    pipeline_name = pipeline.get("name", os.path.basename(pf))
    matched_ls = set()

    # IMPORTANT: Use the exact path you saw in Step 4
    activities = pipeline.get("properties", {}).get("activities", [])

    for activity in activities:
        # --- Direct: activity-level linked service ---
        ls_ref = activity.get("linked_service_name", {})
        if isinstance(ls_ref, dict):
            ref_name = ls_ref.get("reference_name", "")
            if ref_name in target_ls_names:
                matched_ls.add(ref_name)

        # Check typeProperties for resource linked service
        type_props = activity.get("type_properties", {}) or activity.get("typeProperties", {})
        for key in ["resource_linked_service", "linked_service_name"]:
            ref = type_props.get(key, {})
            if isinstance(ref, dict):
                ref_name = ref.get("reference_name", "") or ref.get("referenceName", "")
                if ref_name in target_ls_names:
                    matched_ls.add(ref_name)

        # --- Indirect: dataset references ---
        for ds_field in ["dataset", "inputs", "outputs"]:
            ds_ref = type_props.get(ds_field)
            if ds_ref is None:
                continue
            refs = ds_ref if isinstance(ds_ref, list) else [ds_ref]
            for ref in refs:
                if isinstance(ref, dict):
                    ds_name = ref.get("reference_name", "") or ref.get("referenceName", "")
                    ls_name = ds_to_ls.get(ds_name, "")
                    if ls_name in target_ls_names:
                        matched_ls.add(ls_name)
                        print(f"  [{pipeline_name}] dataset '{ds_name}' -> LS '{ls_name}' (MATCH)")

    if matched_ls:
        results[pipeline_name] = sorted(matched_ls)
        print(f"[MATCH] {pipeline_name}: {sorted(matched_ls)}")
    else:
        print(f"[SKIP] {pipeline_name}: no match")

print(f"\n=== Results: {len(results)} pipelines matched ===")
print(json.dumps(results, indent=2))

# --- Write results to file ---
out_path = os.path.join(session_dir, "results.json")
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"Results written to {out_path}")
```

### Step 6: If exec_python Fails or Returns Nothing — Debug and Retry

This should be rare if Step 4 was done properly. If it does happen:

- Re-read the pipeline (PICK DIFFERENT PIPELINES!!!) /dataset files from Step 4 output, compare with the script's field names
- Fix the mismatch and re-run
- Maximum 2 retries (3 total attempts including the first run)
- If retries occur, the last successful run's output is the final result. `results.json` always reflects the latest run.

### Step 7: Present Results

After a successful exec_python run, present the results from its printed output directly as a readable table. Do NOT call exec_python or read_file again just to format — the output is already available.

If the print output is unclear (e.g. truncated or mixed with too many debug logs), fall back to `read_file("results.json")`.

## How Linked Services Appear in Pipelines

There are two ways a pipeline can reference a linked service:

1. **Direct (activity-level)**: The activity itself has a `linked_service_name` field, or its `typeProperties` contain `resource_linked_service` or similar fields. Common for Web Activities, Azure Function calls, etc.

2. **Indirect (via dataset)**: The activity references a dataset (through `dataset`, `inputs`, or `outputs`), and the dataset points to a linked service. Common for Copy Activities, Lookup, etc.

Both paths must be checked for complete results.

**Note**: Field names may vary between SDK versions or REST API responses. If the script fails, always verify by reading actual files before retrying.

## Important Notes

- Always call all three list tools in parallel (Step 2) for efficiency
- The `exec_python` script should log every pipeline it checks for debuggability
- If the user asks about a specific version (e.g. "Snowflake v2 only"), use `adf_linked_service_get` to inspect the full definition and distinguish versions
- Dataset count is typically small, so saving all datasets in one file is fine
