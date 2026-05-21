/**
 * CategoryFilter: sidebar filter component for tool categories.
 */

import type { CategoryCount } from "./types";

interface CategoryFilterProps {
  categories: CategoryCount[];
  selected: string | null;
  onSelect: (category: string | null) => void;
}

export function CategoryFilter({
  categories,
  selected,
  onSelect,
}: CategoryFilterProps): JSX.Element {
  return (
    <nav className="category-filter" aria-label="Filter by category">
      <h3>Categories</h3>
      <button
        className={selected === null ? "active" : ""}
        onClick={() => onSelect(null)}
      >
        All
        <span className="count">
          {categories.reduce((sum, c) => sum + c.count, 0)}
        </span>
      </button>
      {categories.map((cat) => (
        <button
          key={cat.category}
          className={selected === cat.category ? "active" : ""}
          onClick={() =>
            onSelect(selected === cat.category ? null : cat.category)
          }
        >
          {cat.category}
          <span className="count">{cat.count}</span>
        </button>
      ))}
    </nav>
  );
}
