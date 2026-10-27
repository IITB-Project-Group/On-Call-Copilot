"""Run golden queries through the real retrieval pipeline and report Recall@k."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from knowledge.retrieval.contracts import RetrievalResponse

from .loader import GoldenQuery, load_golden_queries
from .metrics import AggregateScore, QueryScore, aggregate_scores, score_query

Retrieve = Callable[[str], RetrievalResponse]


@dataclass(frozen=True)
class EvaluationResult:
    """Per-query scores paired with their queries, plus overall aggregates."""

    k: int
    scored: tuple[tuple[GoldenQuery, QueryScore], ...]
    overall: AggregateScore

    def aggregate_by(self, attribute: str) -> dict[str, AggregateScore]:
        """Aggregate scores grouped by a GoldenQuery attribute such as kind or split."""
        groups: dict[str, list[QueryScore]] = defaultdict(list)
        for query, score in self.scored:
            groups[str(getattr(query, attribute))].append(score)
        return {name: aggregate_scores(scores, self.k) for name, scores in sorted(groups.items())}


def evaluate(
    queries: Sequence[GoldenQuery],
    retrieve: Retrieve,
    k: int = 5,
) -> EvaluationResult:
    """Retrieve each query once and score the top-k unique documents."""
    scored = []
    for query in queries:
        response = retrieve(query.query)
        scored.append((query, score_query(query, [p.doc_id for p in response.passages], k)))
    return EvaluationResult(
        k=k,
        scored=tuple(scored),
        overall=aggregate_scores([score for _, score in scored], k),
    )


def format_report(result: EvaluationResult) -> str:
    """Render per-query outcomes, misses, and aggregates as plain text."""
    k = result.k
    lines = [f"Recall@{k} evaluation ({result.overall.query_count} queries)", ""]
    for query, score in result.scored:
        status = "OK  " if not score.missed_docs else ("PART" if score.hit else "MISS")
        line = f"{status} {query.id} [{query.kind}/{query.split}] recall={score.recall:.2f}"
        if score.missed_docs:
            line += f" missed={', '.join(score.missed_docs)}"
        lines.append(line)

    lines += [
        "",
        f"Overall   Recall@{k}={result.overall.mean_recall:.3f}  Hit@{k}={result.overall.hit_rate:.3f}",
    ]
    for attribute in ("kind", "split"):
        for name, aggregate in result.aggregate_by(attribute).items():
            lines.append(
                f"{attribute}={name:<12} n={aggregate.query_count:<3} "
                f"Recall@{k}={aggregate.mean_recall:.3f}  Hit@{k}={aggregate.hit_rate:.3f}"
            )
    return "\n".join(lines)


def compare(
    queries: Sequence[GoldenQuery],
    retrievers: dict[str, Retrieve],
    k: int = 5,
) -> dict[str, EvaluationResult]:
    """Evaluate the same queries once per named retriever."""
    return {label: evaluate(queries, retrieve, k) for label, retrieve in retrievers.items()}


def format_comparison(results: dict[str, EvaluationResult]) -> str:
    """Render overall scores and per-query recall side by side for each configuration."""
    labels = list(results)
    k = next(iter(results.values())).k
    lines = [f"Recall@{k} comparison", ""]
    lines.append(f"{'config':<22}{'queries':>8}{f'Recall@{k}':>12}{f'Hit@{k}':>10}")
    for label, result in results.items():
        overall = result.overall
        lines.append(
            f"{label:<22}{overall.query_count:>8}{overall.mean_recall:>12.3f}{overall.hit_rate:>10.3f}"
        )

    lines += ["", f"{'query':<8}" + "".join(f"{label:>22}" for label in labels)]
    for index, (query, _) in enumerate(results[labels[0]].scored):
        cells = "".join(f"{results[label].scored[index][1].recall:>22.2f}" for label in labels)
        lines.append(f"{query.id:<8}{cells}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Evaluate the pipeline; makes live OpenRouter calls per query and configuration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5, help="Rank cutoff in unique documents")
    parser.add_argument("--split", choices=("dev", "heldout"), help="Only evaluate one split")
    parser.add_argument(
        "--rewrite-counts",
        type=int,
        nargs="+",
        metavar="N",
        help="Compare these query_rewrite_count values instead of using the YAML setting",
    )
    args = parser.parse_args(argv)

    queries = load_golden_queries()
    if args.split:
        queries = [query for query in queries if query.split == args.split]

    from knowledge.retrieval.runbooks_kb_tool import create_runbooks_kb_tool
    from knowledge.retrieval.runtime import initialize_retrieval_service

    if not args.rewrite_counts:
        print(format_report(evaluate(queries, create_runbooks_kb_tool(), args.k)))
        return 0

    retrievers = {
        f"rewrite_count={count}": create_runbooks_kb_tool(
            initialize_retrieval_service(query_rewrite_count=count)
        )
        for count in dict.fromkeys(args.rewrite_counts)
    }
    results = compare(queries, retrievers, args.k)
    print(format_comparison(results))
    for label, result in results.items():
        print(f"\n== {label} ==\n{format_report(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
