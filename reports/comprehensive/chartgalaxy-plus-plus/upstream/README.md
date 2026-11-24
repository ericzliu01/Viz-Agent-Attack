---
license: cc-by-nc-4.0
language:
- en
task_categories:
- image-to-text
- visual-question-answering
pretty_name: ChartGalaxy++
size_categories:
- 100K<n<1M
tags:
- charts
- infographic
- scene-graph
---

<h1 align="center">ChartGalaxy++</h1>

<p align="center"><strong>A Richly Annotated Dataset for Chart Understanding and Generation</strong></p>

<p align="center"><a href="https://github.com/ChartGalaxyPP/ChartGalaxyPlusPlus">Project</a> &nbsp; · &nbsp; <a href="https://huggingface.co/ChartGalaxyPP/ChartGalaxyPlusPlus-Image2SceneGraph">Image2SceneGraph model</a> &nbsp; · &nbsp; <a href="https://github.com/ChartGalaxyPP/ChartGalaxyPlusPlus/releases/tag/v1.0">Application data</a> &nbsp; · &nbsp; <a href="https://huggingface.co/datasets/ChartGalaxyPP/ChartGalaxyPlusPlus/blob/main/USAGE.md">Loading guide</a></p>

**ChartGalaxy++ connects what is in an infographic chart with how it is organized.** Each chart is paired with a scene graph: visual elements and semantic groups form the nodes, while hierarchical and spatial relationships connect them. These annotations support chart structure prediction, visual question answering, and evaluation of image generation.

| Infographic charts | Annotated nodes | Relationships |
| :---: | :---: | :---: |
| **217,195** | **18.90 million** | **39.99 million** |

## Explore the dataset

![Eight synthetic infographic charts with varied chart structures, editorial layouts, typography, and illustrations](assets/gallery.png)

*Selected synthetic examples from the released PNGs, shown in full. The gallery spans compact comparisons, layered circular charts, dense radial marks, and illustrated narratives. [View at full resolution](assets/gallery.png) · [Sample identities](assets/sources.json)*

## What is annotated?

![A pasta-production infographic annotated with text and image elements, semantic groups, node attributes, hierarchy, and spatial relationships](assets/annotation.png)

*The pasta-production example from the paper: each country groups a value, a pasta image, a flag, and a country label. The scene graph records these groups, element attributes, and hierarchical and spatial relationships. [Enlarge](assets/annotation.png)*

| Layer | Annotation content |
| --- | --- |
| **Visual elements** | Text, images, and shapes with bounding boxes, semantic roles, text content, and appearance attributes |
| **Semantic groups** | Charts, axes, legends, legend items, data items, series, and panels |
| **Hierarchy** | Parent–child links connecting elements to groups and the chart composition |
| **Spatial relationships** | Relative position, alignment, overlap, and Boolean proximity (`is_near`) |

See the [annotation guide](ANNOTATION_GUIDE.md), [JSON schema](scene_graph.schema.json), and [data format](DATA_FORMAT.md) for all fields and coordinate conventions.

## Dataset at a glance

| Split | Real charts | Synthetic charts | Total |
| --- | ---: | ---: | ---: |
| Train | 56,244 | 159,951 | 216,195 |
| Test | 500 | 500 | 1,000 |
| **Total** | **56,744** | **160,451** | **217,195** |

**Real charts: URLs + annotation JSON. Synthetic charts: PNG + annotation JSON.** The main dataset is distributed in 926 independently extractable `tar.gz` shards. `sample_index.jsonl.gz` maps each sample ID to its shard and member files. The separate QA package provides image URLs without image files; unavailable URLs are left empty.


## Get started

Install the download client with `pip install huggingface_hub`. Start with one standalone example before downloading shards:

```python
import json
from huggingface_hub import HfApi, hf_hub_download

repo = "ChartGalaxyPP/ChartGalaxyPlusPlus"
revision = HfApi().dataset_info(repo).sha
def download(name):
    return hf_hub_download(repo, name, repo_type="dataset", revision=revision)

image_path = download("examples/01-layout/image.png")
graph_path = download("examples/01-layout/scene_graph.json")
spatial_path = download("examples/01-layout/spatial_relations.json")
with open(graph_path, encoding="utf-8") as f:
    graph = json.load(f)
nodes = graph["compositional_deconstruction"]["nodes"]
print(f"{len(nodes)} explicit nodes", image_path)
```

The example is an existing training record, not an additional sample. To load any chart, use the [sample index](sample_index.jsonl.gz) and the [shard-loading example](USAGE.md). Bounding boxes in dataset annotations use **`[y0, x0, y1, x1]`, normalized to 0–1000**.

<details>
<summary>Download the complete dataset</summary>

```python
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id=repo,
    repo_type="dataset",
    revision=revision,
    local_dir="chartgalaxy-plus-plus",
)
```

The data shards total approximately 105 GB. The release includes shard hashes in [manifest.json](manifest.json). See [USAGE.md](USAGE.md) for extraction and integrity checks.

</details>

## What can you do with it?

| Application | What the scene graph enables | Released resource |
| --- | --- | --- |
| **Image-to-scene-graph prediction** | Recover elements, semantic groups, and chart hierarchy | [Image2SceneGraph model](https://huggingface.co/ChartGalaxyPP/ChartGalaxyPlusPlus-Image2SceneGraph); [1,000-chart benchmark](https://github.com/ChartGalaxyPP/ChartGalaxyPlusPlus/tree/main/applications/image_to_scene_graph) |
| **Infographic question answering** | Associate text and marks through explicit groups and relationships | [1,266 questions, reference answers, and image URLs](https://github.com/ChartGalaxyPP/ChartGalaxyPlusPlus/tree/main/applications/qa) |
| **Scene graph preservation** | Evaluate structural fidelity in generated infographic charts | [11-model benchmark and generated outputs](https://github.com/ChartGalaxyPP/ChartGalaxyPlusPlus/tree/main/applications/scene_graph_preservation) |

See the [project page](https://github.com/ChartGalaxyPP/ChartGalaxyPlusPlus#three-applications) for qualitative results and links to all three application packages. Under the paper's evaluation protocol, the released Image2SceneGraph model achieves **89.4% node F1, 85.1% hierarchy F1, and 88.0% spatial F1**.

## Annotation and release notes

<details>
<summary>Exact annotation counts and release notes</summary>

- **Nodes:** 15,591,656 visual elements + 3,088,632 explicit groups + 217,195 implicit roots = 18,897,483.
- **Relationships:** 18,680,288 parent links + 21,308,862 stored spatial records = 39,989,150. Unrecorded pairs are not negative labels.
- `is_near` is Boolean. Positive-area overlaps and containment are excluded; both absolute and relative distance thresholds must hold. The format guide specifies the rule.
- The 1,000-chart test set, comprising 500 real and 500 synthetic charts, has been manually verified. `human_gold` is true for the test split and false for the training split.
- Generated replacement illustrations and their affected annotations are included in the main dataset. Historical benchmark packages retain the identities of their evaluated inputs; use their supplied references when inspecting reported results.
- Real-image references are supplied without checking their current availability. Source pages, direct image URLs, and missing references are distinguished in the format guide.

</details>


This release contains images or image references, scene graph annotations, and spatial records. Underlying data-table files and annotation/training/evaluation pipeline code are not included. The gallery is a curated visual preview, not a random sample or annotation-quality evaluation.

## License

Contributed annotations are licensed under **CC BY-NC 4.0**. Third-party chart content and required upstream attributions retain their respective rights; see [LICENSE](LICENSE) and [license and sources](LICENSE_AND_SOURCES.md).
