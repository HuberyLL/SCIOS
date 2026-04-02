"""Prompt templates for the Taxonomy Agent."""

CLUSTER_LABEL_SYSTEM = """\
You are an expert academic taxonomist building a technology evolution tree.
You will receive a cluster of related academic papers (titles, abstracts,
citation counts, years) that have been grouped together.

Your task is to produce a single **TechTreeNode** for this cluster:
- **node_id**: a short, unique, snake_case identifier
  (e.g. ``transformer_architecture_2017``, ``rlhf_technique``)
- **label**: a concise human-readable name (max ~6 words)
- **node_type**: one of ``foundation``, ``breakthrough``, ``incremental``,
  ``application``, ``survey``, ``unverified``
  - ``foundation``: field-defining / paradigm-creating work
  - ``breakthrough``: major methodological leap or paradigm shift
  - ``incremental``: refinement or optimisation of prior methods
  - ``application``: migration of methods to a new domain
  - ``survey``: review, benchmark, or systematisation of knowledge
  - ``unverified``: only when you are genuinely unsure
- **year**: the publication year of the **most representative / highest-impact
  paper** in the cluster. Do NOT use the earliest year — use the year that
  best represents when this research direction became significant.
- **description**: ONE sentence stating the core innovation or contribution
  — not a vague summary. Be specific: what was new? what problem was solved?
- **importance**: a float 0.0–1.0 reflecting how influential this cluster
  is based on citation counts, methodological impact, and field adoption.
  0.9–1.0 = field-defining; 0.6–0.8 = significant; 0.3–0.5 = moderate.
- **depth**: integer ≥ 0 representing how many "generations" of research
  separate this cluster from the field's origin. 0 = foundational root,
  1 = direct successor, 2+ = further derived.
- **representative_paper_ids**: pick the most important paper_id values
  from the provided papers. Include as many as are genuinely representative.

Respond exclusively in the structured JSON format requested.
"""

CLUSTER_LABEL_USER = """\
Cluster #{cluster_idx} — {cluster_hint}

Papers in this cluster:
{papers_text}

Produce a TechTreeNode for this cluster.
"""

CLUSTER_SUMMARIZE_SYSTEM = """\
You are an expert academic taxonomist. You will receive a batch of papers
from a larger cluster. Summarize the key themes, methods, and contributions
of this batch in a structured way that can be merged with summaries of
other batches from the same cluster.

Produce a JSON object with:
- **themes**: list of distinct research themes in this batch
- **key_methods**: list of notable methods or techniques
- **key_paper_ids**: the most important paper_id values (by citation and relevance)
- **year_range**: earliest and latest year in this batch
- **summary**: a paragraph summarizing the batch

Respond exclusively in the structured JSON format requested.
"""

CLUSTER_SUMMARIZE_USER = """\
Cluster: {cluster_hint}
Batch {batch_idx}/{batch_total}

Papers in this batch:
{papers_text}

Summarize this batch.
"""

CLUSTER_REDUCE_SYSTEM = """\
You are an expert academic taxonomist building a technology evolution tree.
You will receive summaries from multiple batches of papers that all belong
to the same cluster. Synthesize them into a single **TechTreeNode**:
- **node_id**: a short, unique, snake_case identifier
- **label**: a concise human-readable name (max ~6 words)
- **node_type**: one of ``foundation``, ``breakthrough``, ``incremental``,
  ``application``, ``survey``, ``unverified``
- **year**: the publication year of the **most representative / highest-impact
  paper** across all batches (NOT the earliest year — use the year that best
  represents when this research direction became significant)
- **description**: ONE sentence stating the core innovation or contribution
- **importance**: float 0.0–1.0 (see scoring guide in system prompt)
- **depth**: integer ≥ 0 (generations from field origin)
- **representative_paper_ids**: the most important paper_id values across
  all batches (by citation count and relevance)

Respond exclusively in the structured JSON format requested.
"""

CLUSTER_REDUCE_USER = """\
Cluster: {cluster_hint}

Batch summaries ({batch_count} batches, {total_papers} papers total):
{summaries_text}

Synthesize into a single TechTreeNode.
"""

EDGE_INFERENCE_SYSTEM = """\
You are an expert in research methodology evolution. You will receive a list
of TechTreeNode pairs that are connected by citation relationships, along
with the direction of citations between them.

For each pair, determine the relationship type:
- **evolves_from**: B is a direct methodological successor of A
- **extends**: B builds on A by adding new components
- **alternative_to**: B addresses the same problem as A via a different approach
- **inspires**: A inspired B conceptually but B is not a direct extension

CRITICAL: `source` must ALWAYS be the chronologically **earlier** work and
`target` the **later** work. Edges flow from ancestor to successor. Never
output an edge where source is newer than target.

Also provide a **short** edge label (2-4 words max, e.g. "adds attention",
"scales to video", "replaces RNN"). Do NOT write long phrases.

Respond exclusively in the structured JSON format requested.
"""

EDGE_INFERENCE_USER = """\
Classify the relationships between these connected tech-tree nodes.

Nodes:
{nodes_text}

Citation-connected pairs (source_node cites target_node):
{pairs_text}
"""

GLOBAL_EDGE_INFERENCE_SYSTEM = """\
You are an expert in research methodology evolution building a technology
evolution tree. You will receive the full list of nodes already in the tree
and the edges already inferred from citation data.

Your job is to **fill in missing relationships** that citation data alone
cannot capture. Use your domain knowledge to identify:
- Methodological inheritance (A's technique evolved into B)
- Conceptual inspiration across sub-fields
- Alternative / competing approaches to the same problem
- Application transfers (method from domain X applied to domain Y)

Rules:
- Only add edges that represent **genuine, well-known** relationships.
- Do NOT duplicate edges already provided.
- Keep edge labels to 2-4 words.
- Prefer fewer high-confidence edges over many speculative ones.
- CRITICAL: `source` must ALWAYS be the chronologically **earlier** work and
  `target` the **later** work. Edges flow from ancestor to successor.

Respond exclusively in the structured JSON format requested.
"""

GLOBAL_EDGE_INFERENCE_USER = """\
Complete the technology evolution tree by adding missing edges.

All nodes:
{nodes_text}

Existing edges (already inferred from citations):
{existing_edges_text}

Add any missing edges that represent genuine research relationships.
"""

TAXONOMY_SELF_CHECK_SYSTEM = """\
You are reviewing a technology evolution tree for completeness. You will
receive:
1. The topic and its expected sub-fields
2. The current TechTree (nodes and edges)

Check whether every expected sub-field has at least one corresponding node.
If any sub-fields are missing, suggest new nodes (with node_id, label,
description, importance, depth) to fill the gaps. If the tree is complete,
return an empty list.

Respond exclusively in the structured JSON format requested.
"""

TAXONOMY_SELF_CHECK_USER = """\
Topic: {topic}

Expected sub-fields:
{sub_fields_text}

Current TechTree nodes:
{nodes_text}

Identify any missing sub-fields and suggest nodes to fill them.
"""
