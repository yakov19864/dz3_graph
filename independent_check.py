#!/usr/bin/env python3
"""
independent_check.py

Независимая проверка графа зависимостей с помощью библиотеки networkx.

"""

import sys

try:
    import networkx as nx
except ImportError:
    print("Ошибка: библиотека networkx не установлена.")
    print("Установите её командой: pip install networkx")
    sys.exit(1)

import depgraph


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 independent_check.py <путь_к_каталогу>")
        print("Пример: python3 independent_check.py /Users/misha/Desktop/dz3_analyzer_v2/scrapy/scrapy")
        sys.exit(1)

    path = sys.argv[1]

    # Строим граф через нашу утилиту
    g = depgraph.build_graph(path)

    # Создаём граф в networkx
    G = nx.DiGraph()
    G.add_nodes_from(g.vertices)

    for a, targets in g.adj.items():
        for b in targets:
            G.add_edge(a, b)

    # === Сравнение базовых параметров ===
    print("=== Независимая проверка через networkx ===")
    print()

    my_vertices = len(g.vertices)
    nx_vertices = G.number_of_nodes()
    print(f"Vertices: {nx_vertices} (утилита: {my_vertices}, {'совпало' if my_vertices == nx_vertices else 'НЕ СОВПАЛО'})")

    my_edges = sum(len(x) for x in g.adj.values())
    nx_edges = G.number_of_edges()
    print(f"Edges: {nx_edges} (утилита: {my_edges}, {'совпало' if my_edges == nx_edges else 'НЕ СОВПАЛО'})")

    my_weak = depgraph.weak_components(g)
    nx_weak = nx.number_weakly_connected_components(G)
    print(f"Weakly connected components: {nx_weak} (утилита: {my_weak}, {'совпало' if my_weak == nx_weak else 'НЕ СОВПАЛО'})")

    print()

    # === Проверка циклов ===
    # Ищем сильно связные компоненты размером > 1 (это циклы)
    cyclic_components = []
    for comp in nx.strongly_connected_components(G):
        if len(comp) > 1:
            cyclic_components.append(comp)
        elif len(comp) == 1:
            v = next(iter(comp))
            if G.has_edge(v, v):
                cyclic_components.append(comp)

    has_cycle = len(cyclic_components) > 0
    print(f"Has cycles: {has_cycle}")

    # Проверяем наличие циклов через алгоритм Кана в нашей утилите
    batches, remaining, processed = depgraph.kahn_batches(g)
    my_has_cycle = len(remaining) > 0
    print(f"Утилита нашла циклы: {my_has_cycle}")

    if has_cycle == my_has_cycle:
        print("Наличие циклов: совпало")
    else:
        print("Наличие циклов: НЕ СОВПАЛО")

    print()

    # === Проверка топологического порядка ===
    try:
        generations = list(nx.topological_generations(G))
        ordered_nodes = sum(len(x) for x in generations)

        print("Topological order possible: True")
        print(f"Topological generations: {len(generations)}")
        print(f"Topological order length: {ordered_nodes}")

        print(f"Утилита: пачек = {len(batches)}, обработано файлов = {processed}")

        if len(generations) == len(batches):
            print("Число пачек: совпало")
        else:
            print("Число пачек: НЕ СОВПАЛО")

    except nx.NetworkXUnfeasible:
        print("Topological order possible: False")
        print("Reason: graph has cycles")

        if remaining:
            print(f"Утилита также не смогла построить полный порядок (осталось файлов: {len(remaining)})")
            print("Топологический порядок: совпало (оба невозможны)")
        else:
            print("Утилита построила полный порядок, но networkx не смог: НЕ СОВПАЛО")

    print()
    print("=== Проверка завершена ===")


if __name__ == "__main__":
    main()
