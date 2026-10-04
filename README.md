# Утилита для анализа зависимостей графа

Утилита командной строки для построения графа зависимостей по исходному коду 

## Возможности

- **`stats`** — построение графа и вывод статистики: число вершин (Vertices), ребер (Edges), средняя степень (Average degree), файлы без зависимостей (Files without dependencies), файлы, от которых никто не зависит (Files nobody depends on), число слабосвязных компонент (Weakly connected components).
- **`impact`** — анализ влияния изменения файла: какие файлы будут затронуты, с разбивкой по слоям зависимости.
- **`cycles`** — поиск циклических зависимостей в проекте.
- **`order`** — определение порядка сборки проекта с разбивкой на параллельные пачки.

## Установка

Для работы утилиты требуется только стандартная библиотека Python 3

Запуск
(venv) misha@192 hw3-graph-deps % python depgraph.py stats /Users/misha/Desktop/dz3_analyzer_v2/scrapy/scrapy

Результат
Vertices: 178
Edges: 875
Average degree: 9.831
Files without dependencies: 22
Files nobody depends on: 64
Weakly connected components: 9

