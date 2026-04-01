import type {
  DynamicResearchLandscape,
  LandscapeIncrement,
} from "@/types";

/**
 * Immutably merge a `LandscapeIncrement` into an existing
 * `DynamicResearchLandscape`, returning a brand-new object.
 *
 * 1. Reset existing `is_new` flags to `false`.
 * 2. Append new papers / nodes / scholars / comparisons / gaps (dedup by ID).
 * 3. Append new edges.
 * 4. Update `meta.paper_count`.
 */
export function mergeLandscapeIncrement(
  base: DynamicResearchLandscape,
  increment: LandscapeIncrement,
): DynamicResearchLandscape {
  const hasDelta =
    increment.new_papers.length > 0 ||
    increment.new_tech_nodes.length > 0 ||
    increment.new_tech_edges.length > 0 ||
    increment.new_scholars.length > 0 ||
    increment.new_collab_edges.length > 0 ||
    increment.new_comparisons.length > 0 ||
    increment.new_gaps.length > 0;
  if (!hasDelta) return base;

  // --- Reset existing is_new flags ---
  const existingNodes = base.tech_tree.nodes.map((n) => ({
    ...n,
    is_new: false,
  }));
  const existingScholars = base.collaboration_network.nodes.map((s) => ({
    ...s,
    is_new: false,
  }));

  // --- Papers (dedup by paper_id) ---
  const paperIds = new Set(base.papers.map((p) => p.paper_id));
  const mergedPapers = [...base.papers];
  for (const p of increment.new_papers) {
    if (!paperIds.has(p.paper_id)) {
      paperIds.add(p.paper_id);
      mergedPapers.push(p);
    }
  }

  // --- Tech tree nodes (dedup by node_id) ---
  const nodeIds = new Set(existingNodes.map((n) => n.node_id));
  const mergedNodes = [...existingNodes];
  for (const n of increment.new_tech_nodes) {
    if (!nodeIds.has(n.node_id)) {
      nodeIds.add(n.node_id);
      mergedNodes.push({ ...n, is_new: true });
    }
  }

  // --- Tech tree edges (dedup by semantic signature) ---
  const techEdgeKeys = new Set(
    base.tech_tree.edges.map(
      (e) => `${e.source}|${e.target}|${e.relation}|${e.label}`,
    ),
  );
  const mergedTechEdges = [...base.tech_tree.edges];
  for (const e of increment.new_tech_edges) {
    const key = `${e.source}|${e.target}|${e.relation}|${e.label}`;
    if (!techEdgeKeys.has(key)) {
      techEdgeKeys.add(key);
      mergedTechEdges.push(e);
    }
  }

  // --- Scholars (merge by scholar_id) ---
  const scholarIndex = new Map<string, number>();
  const mergedScholars = [...existingScholars];
  mergedScholars.forEach((s, idx) => scholarIndex.set(s.scholar_id, idx));
  for (const s of increment.new_scholars) {
    const idx = scholarIndex.get(s.scholar_id);
    if (idx === undefined) {
      scholarIndex.set(s.scholar_id, mergedScholars.length);
      mergedScholars.push({ ...s, is_new: true });
      continue;
    }
    const existing = mergedScholars[idx];
    const mergedTopPaperIds = Array.from(
      new Set([...s.top_paper_ids, ...existing.top_paper_ids]),
    ).slice(0, 5);
    mergedScholars[idx] = {
      ...existing,
      affiliations: Array.from(
        new Set([...existing.affiliations, ...s.affiliations]),
      ).sort(),
      paper_count: existing.paper_count + s.paper_count,
      citation_count: existing.citation_count + s.citation_count,
      top_paper_ids: mergedTopPaperIds,
      is_new: false,
    };
  }

  // --- Collaboration edges (merge by undirected pair) ---
  const collabIndex = new Map<string, number>();
  const mergedCollabEdges = [...base.collaboration_network.edges];
  mergedCollabEdges.forEach((e, idx) => {
    const key = [e.source, e.target].sort().join("|");
    collabIndex.set(key, idx);
  });
  for (const e of increment.new_collab_edges) {
    const key = [e.source, e.target].sort().join("|");
    const idx = collabIndex.get(key);
    if (idx === undefined) {
      collabIndex.set(key, mergedCollabEdges.length);
      mergedCollabEdges.push(e);
      continue;
    }
    const existing = mergedCollabEdges[idx];
    mergedCollabEdges[idx] = {
      ...existing,
      weight: existing.weight + e.weight,
      shared_paper_ids: Array.from(
        new Set([...existing.shared_paper_ids, ...e.shared_paper_ids]),
      ),
    };
  }

  // --- Comparisons (dedup by paper_id) ---
  const compIds = new Set(
    base.comparison_matrix.papers.map((c) => c.paper_id),
  );
  const mergedComparisons = [...base.comparison_matrix.papers];
  for (const c of increment.new_comparisons) {
    if (!compIds.has(c.paper_id)) {
      compIds.add(c.paper_id);
      mergedComparisons.push(c);
    }
  }

  // --- Research gaps (dedup by gap_id) ---
  const gapIds = new Set(base.research_gaps.gaps.map((g) => g.gap_id));
  const mergedGaps = [...base.research_gaps.gaps];
  for (const g of increment.new_gaps) {
    if (!gapIds.has(g.gap_id)) {
      gapIds.add(g.gap_id);
      mergedGaps.push(g);
    }
  }

  const mergedSources = [...base.sources];
  const sourceSet = new Set(mergedSources);
  for (const p of increment.new_papers) {
    if (p.url && !sourceSet.has(p.url)) {
      sourceSet.add(p.url);
      mergedSources.push(p.url);
    }
    if (p.doi && !sourceSet.has(p.doi)) {
      sourceSet.add(p.doi);
      mergedSources.push(p.doi);
    }
  }

  return {
    meta: {
      ...base.meta,
      paper_count: mergedPapers.length,
      version: base.meta.version + 1,
    },
    tech_tree: { nodes: mergedNodes, edges: mergedTechEdges },
    collaboration_network: {
      nodes: mergedScholars,
      edges: mergedCollabEdges,
    },
    comparison_matrix: {
      ...base.comparison_matrix,
      papers: mergedComparisons,
    },
    research_gaps: {
      ...base.research_gaps,
      gaps: mergedGaps,
    },
    papers: mergedPapers,
    sources: mergedSources,
  };
}
