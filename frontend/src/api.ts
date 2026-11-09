// Appels à l'API FastAPI. Le cookie de session est envoyé automatiquement (même origine).

export type User = {
  id: string;
  username: string;
  display_name: string;
  role: "user" | "super_admin";
};

export type StorageType = "fridge" | "freezer" | "pantry" | "spice_rack" | "fruit_bowl" | "other";

export type Location = { id: string; name: string; storage_type: StorageType; position: number };

export type Inventory = {
  id: string;
  name: string;
  kind: "personal" | "shared";
  role: "admin" | "contributor" | "member";
  include_in_suggestions: boolean;
  locations: Location[];
};

export type ItemStatus = "ok" | "soon" | "expired" | "best_before_passed";
export type DateType = "use_by" | "best_before" | "estimated";

export type Item = {
  id: string;
  inventory_id: string;
  kind: "ingredient" | "leftover";
  food_id: string | null;
  name: string;
  category_name: string | null;
  quantity: number;
  unit: string;
  units: string[];
  storage_location_id: string;
  entered_on: string;
  expires_on: string;
  date_type: DateType;
  opened_on: string | null;
  status: ItemStatus;
  days_left: number;
};

export type Alerts = { expired: number; soon: number; best_before_passed: number };

export type Food = {
  id: string;
  name: string;
  category_id: string;
  category_name: string;
  reference_unit: "g" | "ml" | "piece";
  units: string[];
  is_private: boolean;
};

export type Category = { id: string; name: string; aisle: string };

export type RemovalReason = "consumed" | "discarded" | "given" | "cooked" | "other";

export type Removal = {
  id: string;
  item_id: string;
  name: string;
  quantity: number;
  unit: string;
  reason: RemovalReason;
  removed_at: string;
  removed_by: string | null;
  undone_at: string | null;
};

export type ItemCreate = {
  kind: "ingredient" | "leftover";
  food_id?: string;
  leftover_name?: string;
  quantity: number;
  unit?: string;
  storage_location_id: string;
  expires_on?: string;
  date_type?: "use_by" | "best_before";
  opened_on?: string;
};

export type ItemUpdate = Partial<{
  quantity: number;
  unit: string;
  storage_location_id: string;
  expires_on: string;
  date_type: "use_by" | "best_before";
  opened_on: string | null;
  leftover_name: string;
}>;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, data));
  return data as T;
}

function errorMessage(status: number, data: unknown): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (status === 422) return "Certains champs ne sont pas valides.";
  return "Une erreur est survenue. Réessaie dans un instant.";
}

export const api = {
  me: () => request<User>("GET", "/api/auth/me"),
  login: (username: string, password: string) => request<User>("POST", "/api/auth/login", { username, password }),
  register: (username: string, display_name: string, password: string) =>
    request<User>("POST", "/api/auth/register", { username, display_name, password }),
  logout: () => request<void>("POST", "/api/auth/logout"),

  inventories: () => request<Inventory[]>("GET", "/api/inventories"),
  items: (inventoryId: string) => request<{ items: Item[]; alerts: Alerts }>("GET", `/api/inventories/${inventoryId}/items`),
  addItem: (inventoryId: string, body: ItemCreate) => request<Item>("POST", `/api/inventories/${inventoryId}/items`, body),
  updateItem: (itemId: string, body: ItemUpdate) => request<Item>("PATCH", `/api/items/${itemId}`, body),
  removeItem: (itemId: string, reason: RemovalReason, quantity?: number, unit?: string) =>
    request<Item>("POST", `/api/items/${itemId}/remove`, { reason, quantity, unit }),
  removals: (inventoryId: string) => request<Removal[]>("GET", `/api/inventories/${inventoryId}/removals`),
  restore: (removalId: string) => request<Item>("POST", `/api/removals/${removalId}/restore`),

  searchFoods: (q: string) => request<Food[]>("GET", `/api/foods?q=${encodeURIComponent(q)}`),
  createFood: (name: string, category_id: string, reference_unit: Food["reference_unit"]) =>
    request<Food>("POST", "/api/foods", { name, category_id, reference_unit }),
  categories: () => request<Category[]>("GET", "/api/food-categories"),
  basics: () => request<Food[]>("GET", "/api/basics"),
};
