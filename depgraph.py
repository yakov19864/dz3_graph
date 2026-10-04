
import argparse
import ast
import os
import sys
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Set

# считаем тестами и исключаем из графа.
TEST_DIRS = {"tests", "test", "__tests__"}

# Чтобы рекурсия в DFS не падала на больших графах.
sys.setrecursionlimit(1_000_000)


@dataclass
class Graph:
    """
    Модель графа:

    Вершина:
    - один .py файл внутри анализируемого каталога.

    Ребро:
    - A -> B означает, что файл A импортирует файл B.
    - То есть ребро направлено от импортирующего файла к импортируемому.
    - Файл A зависит от файла B.
    """
    analysis_root: str
    package_root: str
    package_name: str
    analysis_rel: str
    vertices: List[str]
    adj: Dict[str, Set[str]]


def is_excluded(relpath: str) -> bool:
    """
    Исключаем тесты и тестовые файлы.
    """
    parts = relpath.split("/")

    if any(part in TEST_DIRS for part in parts[:-1]):
        return True

    name = parts[-1]

    if name.startswith("test_"):
        return True

    if name.endswith("_test.py"):
        return True

    if name.endswith(".spec.py"):
        return True

    return False


def find_package_root(analysis_root: str):
    """
    Определяем корень и его имя.

    """
    cur = analysis_root

    if not os.path.isfile(os.path.join(cur, "__init__.py")):
        return cur, os.path.basename(cur)

    while True:
        parent = os.path.dirname(cur)

        if parent == cur:
            break

        if os.path.isfile(os.path.join(parent, "__init__.py")):
            cur = parent
        else:
            break

    return cur, os.path.basename(cur)


def collect_files(analysis_root: str) -> Set[str]:
    """
    Собираем все файлы .py внутри analysis_root,
    исключая тесты и служебные каталоги.
    """
    files: Set[str] = set()

    for dirpath, dirnames, filenames in os.walk(analysis_root):
        rel_dir = os.path.relpath(dirpath, analysis_root).replace(os.sep, "/")

        if rel_dir == ".":
            rel_dir = ""

        dirnames[:] = [
            d for d in dirnames
            if d not in TEST_DIRS and d != "__pycache__"
        ]

        for filename in filenames:
            if not filename.endswith(".py"):
                continue

            if rel_dir == "":
                relpath = filename
            else:
                relpath = f"{rel_dir}/{filename}"

            if is_excluded(relpath):
                continue

            files.add(relpath)

    return files


def build_graph(path: str) -> Graph:
    """
    Строим граф зависимостей по исходному коду.

    Направление ребер:
    A -> B означает, что A зависит от B.
    """
    analysis_root = os.path.abspath(path)

    if not os.path.isdir(analysis_root):
        raise SystemExit(f"Path is not a directory: {analysis_root}")

    package_root, package_name = find_package_root(analysis_root)

    analysis_rel = os.path.relpath(analysis_root, package_root).replace(os.sep, "/")

    if analysis_rel == ".":
        analysis_rel = ""

    files = collect_files(analysis_root)

    def full_rel(relpath: str) -> str:
        """
        Путь файла относительно корня пакета.
        """
        if analysis_rel:
            return f"{analysis_rel}/{relpath}"

        return relpath

    def module_to_file(module: str):
        """
        Преобразует имя модуля в файл внутри анализируемого каталога.
        """
        if not module:
            return None

        parts = module.split(".")

        if parts and parts[0] == package_name:
            parts = parts[1:]

        if not parts:
            candidates = ["__init__.py"]
        else:
            base = "/".join(parts)
            candidates = [
                base + ".py",
                base + "/__init__.py",
            ]

        for cand in candidates:
            if analysis_rel:
                prefix = analysis_rel + "/"

                if not cand.startswith(prefix):
                    continue

                sub = cand[len(prefix):]
            else:
                sub = cand

            if sub in files:
                return sub

        return None

    def resolve_relative(module: str, level: int, relpath: str) -> str:
        """
        Разрешает относительные импорты.
        """
        fr = full_rel(relpath)
        parts = fr.split("/")

        package_parts = parts[:-1]
        base = package_parts[:]

        for _ in range(max(0, level - 1)):
            if base:
                base.pop()

        if module:
            return ".".join([package_name] + base + module.split("."))

        return ".".join([package_name] + base)

    def parse_one(relpath: str) -> Set[str]:
        """
        Разбирает один файл.

        Учитываются только статические импорты:
        - import x.y
        - from x.y import z
        - относительные импорты
        """
        filename = os.path.join(analysis_root, relpath)

        try:
            with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
        except OSError:
            return set()

        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError:
            return set()

        deps: Set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = module_to_file(alias.name)

                    if target:
                        deps.add(target)

            elif isinstance(node, ast.ImportFrom):
                level = node.level or 0
                module = node.module or ""

                if level == 0:
                    full_module = module
                else:
                    full_module = resolve_relative(module, level, relpath)

                target = module_to_file(full_module)

                if target:
                    deps.add(target)

                # Например:
                # from scrapy import spiders
                # может означать импорт подмодуля/пакета spiders.
                for alias in node.names:
                    if alias.name == "*":
                        continue

                    if full_module:
                        sub_module = f"{full_module}.{alias.name}"
                    else:
                        sub_module = alias.name

                    target2 = module_to_file(sub_module)

                    if target2:
                        deps.add(target2)

        deps.discard(relpath)

        return deps

    vertices = sorted(files)
    adj = {v: parse_one(v) for v in vertices}

    return Graph(
        analysis_root=analysis_root,
        package_root=package_root,
        package_name=package_name,
        analysis_rel=analysis_rel,
        vertices=vertices,
        adj=adj,
    )


def build_reverse_adj(g: Graph) -> Dict[str, Set[str]]:
    """
    Обратные ребра нужны для impact.

    Если есть A -> B, то в обратном графе есть B -> A.
    Это значит: если изменить B, то A будет затронут.
    """
    radj: Dict[str, Set[str]] = {v: set() for v in g.vertices}

    for a, targets in g.adj.items():
        for b in targets:
            radj[b].add(a)

    return radj


def weak_components(g: Graph) -> int:
    """
    Число слабосвязных компонент.

    Забываем направление ребер и считаем компоненты обходом.
    """
    undirected: Dict[str, Set[str]] = {v: set() for v in g.vertices}

    for a, targets in g.adj.items():
        for b in targets:
            undirected[a].add(b)
            undirected[b].add(a)

    visited: Set[str] = set()
    count = 0

    for start in g.vertices:
        if start in visited:
            continue

        count += 1

        stack = [start]
        visited.add(start)

        while stack:
            v = stack.pop()

            for to in undirected[v]:
                if to not in visited:
                    visited.add(to)
                    stack.append(to)

    return count


def normalize_vertex(g: Graph, name: str) -> str:
    """
    Приводит пользовательское имя файла к вершине графа.
    """
    raw = name.strip()
    normalized = raw.replace(os.sep, "/")

    candidates = [normalized]

    if normalized.startswith("./"):
        candidates.append(normalized[2:])

    if os.path.isabs(raw):
        try:
            rel = os.path.relpath(raw, g.analysis_root).replace(os.sep, "/")
            candidates.append(rel)
        except ValueError:
            pass

    for cand in candidates:
        if cand in g.vertices:
            return cand

    root_base = os.path.basename(g.analysis_root.rstrip("/\\"))

    for cand in list(candidates):
        if root_base and cand.startswith(root_base + "/"):
            rest = cand[len(root_base) + 1:]

            if rest in g.vertices:
                return rest

    for cand in list(candidates):
        if cand.startswith(g.package_name + "/"):
            rest = cand[len(g.package_name) + 1:]

            if g.analysis_rel and rest.startswith(g.analysis_rel + "/"):
                rest2 = rest[len(g.analysis_rel) + 1:]

                if rest2 in g.vertices:
                    return rest2

            if rest in g.vertices:
                return rest

    exact_suffix = [
        v for v in g.vertices
        if v == normalized or v.endswith("/" + normalized)
    ]

    if len(exact_suffix) == 1:
        return exact_suffix[0]

    base = os.path.basename(normalized)

    base_matches = [
        v for v in g.vertices
        if os.path.basename(v) == base
    ]

    if len(base_matches) == 1:
        return base_matches[0]

    examples = ", ".join(g.vertices[:5])
    raise SystemExit(f"Cannot resolve file {name} to a vertex. Examples: {examples}")


def cmd_stats(args):
    """
    Команда stats.

    Печатает:
    - число вершин;
    - число ребер;
    - среднюю степень вершины;
    - число файлов без зависимостей;
    - число файлов, от которых не зависит никто;
    - число слабосвязных компонент.
    """
    g = build_graph(args.path)

    v_count = len(g.vertices)
    e_count = sum(len(x) for x in g.adj.values())

    if v_count == 0:
        avg_degree = 0.0
    else:
        avg_degree = 2.0 * e_count / v_count

    indeg = {v: 0 for v in g.vertices}

    for targets in g.adj.values():
        for to in targets:
            indeg[to] += 1

    no_dependencies = [
        v for v in g.vertices
        if len(g.adj[v]) == 0
    ]

    nobody_depends_on_me = [
        v for v in g.vertices
        if indeg[v] == 0
    ]

    components = weak_components(g)

    print("Vertices:", v_count)
    print("Edges:", e_count)
    print(f"Average degree: {avg_degree:.3f}")
    print("Files without dependencies:", len(no_dependencies))
    print("Files nobody depends on:", len(nobody_depends_on_me))
    print("Weakly connected components:", components)


def cmd_impact(args):
    """
    Команда impact.

    BFS по обратным ребрам.
    Показывает, какие файлы будут затронуты изменением выбранного файла.
    """
    g = build_graph(args.path)
    target = normalize_vertex(g, args.file)

    radj = build_reverse_adj(g)

    visited = {target}
    q = deque()
    q.append((target, 0))

    layers: List[List[str]] = []

    while q:
        v, layer = q.popleft()

        while len(layers) <= layer:
            layers.append([])

        layers[layer].append(v)

        for to in sorted(radj.get(v, set())):
            if to not in visited:
                visited.add(to)
                q.append((to, layer + 1))

    affected_total = len(visited) - 1

    print("Target:", target)
    print("Affected files (excluding target):", affected_total)

    if affected_total == 0:
        print("No affected files.")
        return

    for i in range(1, len(layers)):
        print()
        print(f"Layer {i}: {len(layers[i])}")

        for filename in sorted(layers[i]):
            print("  ", filename)


def normalize_cycle(cycle: List[str]):
    """
    Приводит цикл к каноническому виду,
    чтобы не считать одинаковые циклы несколько раз.
    """
    c = cycle[:-1]

    if not c:
        return tuple(cycle)

    best = None

    for i in range(len(c)):
        rotated = tuple(c[i:] + c[:i])

        if best is None or rotated < best:
            best = rotated

    return best


def find_cycles(g: Graph) -> List[List[str]]:
    """
    Поиск циклов обходом в глубину с тремя цветами.

    0 - белый, вершина еще не посещена.
    1 - серый, вершина сейчас в стеке обхода.
    2 - черный, вершина полностью обработана.

    Если находим ребро из текущей вершины в серую вершину,
    значит найден цикл.
    """
    color = {v: 0 for v in g.vertices}

    stack: List[str] = []
    position: Dict[str, int] = {}

    cycles: List[List[str]] = []
    seen_cycles = set()

    def dfs(v: str):
        color[v] = 1
        position[v] = len(stack)
        stack.append(v)

        for to in sorted(g.adj.get(v, set())):
            if color[to] == 0:
                dfs(to)

            elif color[to] == 1:
                idx = position.get(to)

                if idx is not None:
                    cycle = stack[idx:] + [to]
                    key = normalize_cycle(cycle)

                    if key not in seen_cycles:
                        seen_cycles.add(key)
                        cycles.append(cycle)

        color[v] = 2
        stack.pop()
        position.pop(v, None)

    for v in g.vertices:
        if color[v] == 0:
            dfs(v)

    return cycles


def cmd_cycles(args):
    """
    Команда cycles.

    Печатает сами циклы вершинами по порядку замыкания.
    Если найден хотя бы один цикл, код возврата 1.
    """
    g = build_graph(args.path)
    cycles = find_cycles(g)

    if not cycles:
        print("No cycles found.")
        sys.exit(0)

    for cycle in cycles:
        print(" -> ".join(cycle))

    sys.exit(1)


def kahn_batches(g: Graph):
    """
    Топологическая сортировка.

    Исходное ребро:
    A -> B означает, что A зависит от B.

    Для сборки используем обратный смысл:
    сначала нужно собрать B, потом A.

    Поэтому считаем входящие степени по зависимостям:
    если у файла нет зависимостей, его можно собирать сразу.
    """
    indegree = {v: 0 for v in g.vertices}
    dependents = {v: set() for v in g.vertices}

    for a, targets in g.adj.items():
        for b in targets:
            dependents[b].add(a)
            indegree[a] += 1

    current = sorted([
        v for v in g.vertices
        if indegree[v] == 0
    ])

    batches: List[List[str]] = []
    processed = 0

    while current:
        batches.append(current)
        processed += len(current)

        next_nodes = set()

        for v in current:
            for to in dependents[v]:
                indegree[to] -= 1

                if indegree[to] == 0:
                    next_nodes.add(to)

        current = sorted(next_nodes)

    remaining = sorted([
        v for v in g.vertices
        if indegree[v] > 0
    ])

    return batches, remaining, processed


def cmd_order(args):
    """
    Команда order.

    Печатает вершины пачками:
    - в первой пачке файлы, которые можно собирать сразу;
    - во второй пачке файлы, которые становятся доступны после первой;
    - и так далее.

    В конце печатается число пачек и отношение числа пачек к числу файлов.
    """
    g = build_graph(args.path)

    batches, remaining, processed = kahn_batches(g)
    v_count = len(g.vertices)

    for i, batch in enumerate(batches, start=1):
        print(f"Batch {i}: {len(batch)}")

        for filename in batch:
            print("  ", filename)

        print()

    batch_count = len(batches)

    if v_count == 0:
        ratio = 0.0
    else:
        ratio = batch_count / v_count

    print("Batches:", batch_count)
    print(f"Batches to files ratio: {batch_count} / {v_count} = {ratio:.3f}")

    if remaining:
        print()
        print("Topological order is impossible because of cycles.")
        print("Remaining files:", len(remaining))

        for filename in remaining:
            print("  ", filename)

        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="depgraph",
        description="Dependency graph analyzer for source code projects.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_stats = subparsers.add_parser(
        "stats",
        help="Build graph and print statistics.",
    )
    p_stats.add_argument("path")
    p_stats.set_defaults(func=cmd_stats)

    p_impact = subparsers.add_parser(
        "impact",
        help="BFS impact analysis.",
    )
    p_impact.add_argument("path")
    p_impact.add_argument("file")
    p_impact.set_defaults(func=cmd_impact)

    p_cycles = subparsers.add_parser(
        "cycles",
        help="Find cycles using DFS.",
    )
    p_cycles.add_argument("path")
    p_cycles.set_defaults(func=cmd_cycles)

    p_order = subparsers.add_parser(
        "order",
        help="Topological order using Kahn algorithm.",
    )
    p_order.add_argument("path")
    p_order.set_defaults(func=cmd_order)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
