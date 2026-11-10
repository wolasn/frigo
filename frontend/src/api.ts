// Appels à l'API FastAPI. Le cookie de session est envoyé automatiquement (même origine).

export type User = {
  id: string;
  username: string;
  display_name: string;
  role: "user" | "super_admin";
};

export type StorageType = "fridge" | "freezer" | "pantry" | "spice_rack" | "fruit_bowl" | "other";

export type Location = { id: string; name: string; storage_type: StorageType; position: number };

export type ManagedLocation = Location & { item_count: number };

export type ShelfLifeRow = { id: string; name: string; default_days: number | null; days: number | null };
export type LocationShelfLife = { location: ManagedLocation; categories: ShelfLifeRow[]; foods: ShelfLifeRow[] };

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
  reserved: number;
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

export type ScanLine = {
  id: string;
  label: string;
  food: Food | null;
  quantity: number | null;
  unit: string | null;
  storage_location_id: string | null;
  expires_on: string | null;
  date_type: DateType | null;
  confidence: number;
  doubtful: boolean;
  question: string | null;
  options: string[];
  merge_with: { item_id: string; expires_on: string } | null;
};

export type PhotoScan = { id: string; inventory_id: string; engine: "claude" | "local"; status: string; lines: ScanLine[]; fallback?: boolean };

export type ScanLineEdit = {
  id: string;
  include: boolean;
  food_id?: string;
  quantity?: number;
  unit?: string;
  storage_location_id?: string;
  expires_on?: string;
  date_type?: DateType;
  merge?: boolean;
};

export type UsageTotals = { calls: number; input_tokens: number; output_tokens: number; cost_usd: number };
export type UserUsage = UsageTotals & { user_id: string | null; username: string; display_name: string | null; recipes: UsageTotals; photos: UsageTotals };
export type AiUsage = { month: string | null; total: UsageTotals; users: UserUsage[] };
export type UsageCall = { created_at: string; kind: "recipe" | "photo"; model: string; input_tokens: number; output_tokens: number; cost_usd: number };

export type AdminSettings = {
  photo_engine: "claude" | "local";
  photo_local_url: string;
  photo_local_model: string;
  photo_local_fallback: boolean;
  ai_recipe_model: "claude-opus-5-5" | "claude-sonnet-5-5" | "claude-haiku-5-5";
};

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

export type RecipeCard = {
  id: string;
  title: string;
  source: "marmiton" | "ai" | "user";
  status: "draft" | "complete";
  is_mine: boolean;
  image_url: string | null;
  external_url: string | null;
  base_servings: number;
  prep_minutes: number | null;
  cook_minutes: number | null;
  difficulty: "easy" | "medium" | "hard" | null;
  is_vegan: boolean;
  is_vegetarian: boolean;
  health_score: number | null;
  rating: number | null;
  comment: string | null;
  is_favorite: boolean;
  is_pinned: boolean;
  times_cooked: number;
  last_cooked_on: string | null;
  servings: number;
  missing: string[];
  expiring_used: string[];
  missing_utensils: string[];
  disliked: string[];
};

export type IngredientStatus = "ok" | "partial" | "missing" | "unknown" | "seasoning" | "infinite";

export type RecipeDetail = RecipeCard & {
  ingredients: { id: string; name: string; raw_text: string; amount: string | null; status: IngredientStatus; expiring: boolean; disliked: boolean }[];
  utensils: { name: string; owned: boolean; optional: boolean }[];
  steps: string[];
  nutrition: {
    per_serving?: Record<string, number | null>;
    points?: { label: string; points: number }[];
    serving_g?: number;
  } | null;
};

export type ProposalQuery = {
  servings: number;
  mode: "inventory" | "purchases";
  max_purchases?: number;
  diet: "none" | "vegetarian" | "vegan";
  include_missing_utensils: boolean;
  inventory_ids?: string[];
  max_difficulty?: "easy" | "medium" | "hard";
  max_minutes?: number;
  min_health?: number;
};

export type Utensil = { id: string; name: string; category: "cooking" | "preparation" | "container"; owned: boolean; is_custom: boolean };

export type MealSlot = "breakfast" | "lunch" | "snack" | "dinner";

export type Meal = {
  id: string;
  meal_date: string;
  slot: MealSlot;
  position: number;
  servings: number;
  status: "planned" | "done" | "cancelled";
  kind: "recipe" | "leftover";
  recipe_id: string | null;
  leftover_item_id: string | null;
  title: string;
  image_url: string | null;
  agenda_id: string | null;
  agenda_name: string;
  planned_by: string | null;
  can_edit: boolean;
  shortages: { name: string; reason: "expires_before" | "insufficient" }[];
};

export type BalanceTile = {
  key: string;
  label: string;
  value: string;
  target: string;
  status: "good" | "warn" | "info";
  hint: string;
  meal_ids: string[];
};

export type WeekBalance = { meal_count: number; analyzed_count: number; unanalyzed_meal_ids: string[]; days: number; tiles: BalanceTile[] };

export type MealAlternative = { recipe: RecipeCard; reasons: string[]; in_stock: boolean };

export type MealDraft = { meal_date: string; slot: MealSlot; recipe: RecipeCard | null; reasons: string[] };

export type SuggestBody = { days: string[]; slots?: MealSlot[]; agenda: string; servings?: number; exclude?: string[]; prefer?: string[] };

export type MealCreate = {
  recipe_id?: string;
  leftover_item_id?: string;
  meal_date: string;
  slot: MealSlot;
  servings: number;
  shared_inventory_id?: string;
};

export type MealChange = Partial<{ meal_date: string; slot: MealSlot; position: number; servings: number }>;

export type ShoppingLine = {
  id: string;
  origin: "generated" | "manual";
  food_id: string | null;
  label: string;
  quantity: number | null;
  unit: string | null;
  aisle: string;
  recommended_purchase_on: string | null;
  is_perishable: boolean;
  expiry_risk: boolean;
  meals: { title: string; meal_date: string }[];
  default_location_id: string | null;
  freeze_from: string | null;
};

export type ShoppingList = { id: string; name: string; inventory_id: string; lines: ShoppingLine[] };

export type PurchasedLine = { id: string; quantity?: number; unit?: string; expires_on?: string; storage_location_id?: string };

export type Role = "admin" | "contributor" | "member";

export type InventoryDetail = {
  id: string;
  name: string;
  kind: "personal" | "shared";
  my_role: Role;
  include_in_suggestions: boolean;
  members: { user_id: string; username: string; display_name: string; role: Role; is_me: boolean }[];
  invitations: { id: string; username: string; display_name: string }[];
};

export type MyInvitation = { id: string; inventory_id: string; inventory_name: string; invited_by: string | null; created_at: string };

export type NotificationSummary = {
  unread: number;
  pending_invitations: number;
  items: { id: string; type: string; message: string; created_at: string; read: boolean }[];
};

export type Preferences = {
  diet: "none" | "vegetarian" | "vegan";
  default_servings: number;
  expiring_soon_days: number;
  thresholds: { category_id: string; category_name: string; days: number }[];
  exclusions: { food_id: string; name: string; reason: "allergy" | "dislike" }[];
  basics: { food_id: string; name: string; removable: boolean }[];
};

export type DbStatus = {
  status: "ok" | "down" | "unknown";
  cause: string | null;
  since: string | null;
  last_check: string | null;
  last_incident_start: string | null;
  last_incident_end: string | null;
  email_error: string | null;
  live?: string | null;
};

export async function statusWithKey(key: string): Promise<DbStatus> {
  const response = await fetch("/api/admin/status", { headers: { "X-Status-Key": key } });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, (data as { detail?: string } | null)?.detail ?? "Accès refusé.");
  return data as DbStatus;
}

export type RecipeInput = {
  title: string;
  servings: number;
  prep_minutes: number | null;
  cook_minutes: number | null;
  difficulty: "easy" | "medium" | "hard" | null;
  image_url: string | null;
  ingredients: { food_id: string | null; text?: string | null; quantity: number | null; unit: string | null; is_optional: boolean }[];
  steps: string[];
  utensils: { utensil_id: string; optional: boolean }[];
  complete: boolean;
};

export type RecipeEdit = Omit<RecipeInput, "ingredients" | "complete"> & {
  id: string;
  status: "draft" | "complete";
  ingredients: { food_id: string | null; food_name: string | null; text: string; quantity: number | null; unit: string | null; units: string[]; is_optional: boolean }[];
  missing: string[];
};

export type MyRecipes = {
  mine: { id: string; title: string; status: "draft" | "complete"; servings: number; is_vegan: boolean; is_vegetarian: boolean; shared_with: number; updated_at: string }[];
  shared_with_me: { id: string; title: string; author: string | null }[];
};

export type RecipeShareOut = { id: string; label: string; kind: "user" | "inventory" };

export type MetaUpdate = Partial<{ rating: number | null; comment: string | null; is_favorite: boolean; is_pinned: boolean }>;

function query(params: Record<string, string | number | boolean | string[] | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else search.append(key, String(value));
  }
  return search.toString();
}

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
  register: (username: string, display_name: string, password: string, invitation?: string) =>
    request<User>("POST", "/api/auth/register", { username, display_name, password, invitation }),
  checkSignupInvitation: (code: string) =>
    request<{ valid: boolean; required: boolean; expires_at: string | null }>(
      "GET",
      `/api/auth/invitations/check?code=${encodeURIComponent(code)}`,
    ),
  createSignupInvitation: () => request<{ code: string; expires_at: string }>("POST", "/api/auth/invitations"),
  logout: () => request<void>("POST", "/api/auth/logout"),

  inventories: () => request<Inventory[]>("GET", "/api/inventories"),
  items: (inventoryId: string) => request<{ items: Item[]; alerts: Alerts }>("GET", `/api/inventories/${inventoryId}/items`),
  addItem: (inventoryId: string, body: ItemCreate) => request<Item>("POST", `/api/inventories/${inventoryId}/items`, body),
  updateItem: (itemId: string, body: ItemUpdate) => request<Item>("PATCH", `/api/items/${itemId}`, body),
  removeItem: (itemId: string, reason: RemovalReason, quantity?: number, unit?: string) =>
    request<Item>("POST", `/api/items/${itemId}/remove`, { reason, quantity, unit }),
  removals: (inventoryId: string) => request<Removal[]>("GET", `/api/inventories/${inventoryId}/removals`),
  restore: (removalId: string) => request<Item>("POST", `/api/removals/${removalId}/restore`),

  warmUpPhotoModel: () => request<{ engine: "claude" | "local"; warming: boolean }>("POST", "/api/photo-scans/warm-up"),
  analyzePhotos: (photos: { media_type: string; data: string }[], inventory_id?: string) =>
    request<PhotoScan>("POST", "/api/photo-scans", { photos, inventory_id }),
  validateScan: (id: string, lines: ScanLineEdit[]) =>
    request<{ added: number; merged: number }>("POST", `/api/photo-scans/${id}/validate`, { lines }),
  cancelScan: (id: string) => request<void>("POST", `/api/photo-scans/${id}/cancel`),
  aiUsage: (month?: string) => request<AiUsage>("GET", `/api/admin/ai-usage?${query({ month })}`),
  aiUsageDetail: (userKey: string, month?: string) =>
    request<UsageCall[]>("GET", `/api/admin/ai-usage/${encodeURIComponent(userKey)}?${query({ month })}`),
  adminSettings: () => request<AdminSettings>("GET", "/api/admin/settings"),
  updateAdminSettings: (body: Partial<AdminSettings>) => request<AdminSettings>("PATCH", "/api/admin/settings", body),
  searchFoods: (q: string, categoryId?: string) =>
    request<Food[]>("GET", `/api/foods?${query({ q, category_id: categoryId || undefined, limit: categoryId ? 100 : undefined })}`),
  createFood: (name: string, category_id: string, reference_unit: Food["reference_unit"]) =>
    request<Food>("POST", "/api/foods", { name, category_id, reference_unit }),
  categories: () => request<Category[]>("GET", "/api/food-categories"),
  basics: () => request<Food[]>("GET", "/api/basics"),

  proposals: (q: ProposalQuery) => request<RecipeCard[]>("GET", `/api/proposals?${query(q)}`),
  favorites: () => request<RecipeCard[]>("GET", "/api/recipes/favorites"),
  recipe: (id: string, servings?: number) => request<RecipeDetail>("GET", `/api/recipes/${id}?${query({ servings })}`),
  updateMeta: (id: string, body: MetaUpdate) => request<RecipeCard>("PUT", `/api/recipes/${id}/meta`, body),
  importRecipe: (url: string) => request<RecipeCard>("POST", "/api/recipes/import", { url }),
  searchRecipes: (q: string) => request<RecipeCard[]>("POST", "/api/recipes/search", { query: q }),
  generateRecipes: (body: { count: number; servings: number; max_purchases: number | null; diet: string; wish?: string }) =>
    request<RecipeCard[]>("POST", "/api/recipes/generate", body),
  discoverRecipes: () => request<{ queries: string[]; recipes: RecipeCard[] }>("POST", "/api/recipes/discover"),

  agenda: (start: string, end: string) => request<Meal[]>("GET", `/api/agenda?${query({ start, end })}`),
  weekBalance: (start: string, agenda: string) => request<WeekBalance>("GET", `/api/agenda/balance?${query({ start, agenda })}`),
  mealAlternatives: (id: string, focus?: string) => request<MealAlternative[]>("GET", `/api/agenda/${id}/alternatives?${query({ focus })}`),
  replaceMeal: (id: string, recipe_id: string, confirm: boolean) =>
    request<{ warnings: string[]; meal: Meal | null }>("POST", `/api/agenda/${id}/replace`, { recipe_id, confirm }),
  suggestMeals: (body: SuggestBody) => request<MealDraft[]>("POST", "/api/agenda/suggest", body),
  pastUnmarked: () => request<Meal[]>("GET", "/api/agenda/past-unmarked"),
  planMeal: (body: MealCreate) => request<Meal>("POST", "/api/agenda", body),
  previewMove: (id: string, body: MealChange) => request<{ warnings: string[] }>("POST", `/api/agenda/${id}/preview-move`, body),
  updateMeal: (id: string, body: MealChange) => request<{ warnings: string[]; meal: Meal }>("PATCH", `/api/agenda/${id}`, body),
  mealDone: (id: string, leftover_portions?: number) => request<Meal>("POST", `/api/agenda/${id}/done`, { leftover_portions }),
  cancelMeal: (id: string) => request<Meal>("POST", `/api/agenda/${id}/cancel`),

  shopping: () => request<ShoppingList[]>("GET", "/api/shopping"),
  addShoppingLine: (label: string, shared_inventory_id?: string) =>
    request<ShoppingLine>("POST", "/api/shopping/manual", { label, shared_inventory_id }),
  deleteShoppingLine: (id: string) => request<void>("DELETE", `/api/shopping/${id}`),
  purchase: (lines: PurchasedLine[]) =>
    request<{ added_to_inventory: number; removed_from_list: number }>("POST", "/api/shopping/purchase", { lines }),

  createSharedInventory: (name: string) => request<InventoryDetail>("POST", "/api/inventories", { name }),
  inventoryDetail: (id: string) => request<InventoryDetail>("GET", `/api/inventories/${id}`),
  renameInventory: (id: string, name: string) => request<InventoryDetail>("PATCH", `/api/inventories/${id}`, { name }),
  deleteInventory: (id: string) => request<void>("DELETE", `/api/inventories/${id}`),
  setIncludeInSuggestions: (id: string, include_in_suggestions: boolean) =>
    request<InventoryDetail>("PUT", `/api/inventories/${id}/me`, { include_in_suggestions }),
  invite: (id: string, username: string) => request<InventoryDetail>("POST", `/api/inventories/${id}/invitations`, { username }),
  cancelInvitation: (id: string, invitationId: string) => request<void>("DELETE", `/api/inventories/${id}/invitations/${invitationId}`),
  changeRole: (id: string, userId: string, role: Role) => request<InventoryDetail>("PATCH", `/api/inventories/${id}/members/${userId}`, { role }),
  removeMember: (id: string, userId: string) => request<void>("DELETE", `/api/inventories/${id}/members/${userId}`),
  myInvitations: () => request<MyInvitation[]>("GET", "/api/invitations"),
  acceptInvitation: (id: string) => request<InventoryDetail>("POST", `/api/invitations/${id}/accept`),
  declineInvitation: (id: string) => request<void>("POST", `/api/invitations/${id}/decline`),
  locations: (inventoryId: string) => request<ManagedLocation[]>("GET", `/api/inventories/${inventoryId}/locations`),
  addLocation: (inventoryId: string, name: string, storage_type: StorageType) =>
    request<ManagedLocation>("POST", `/api/inventories/${inventoryId}/locations`, { name, storage_type }),
  updateLocation: (id: string, body: { name?: string; storage_type?: StorageType }) =>
    request<ManagedLocation>("PATCH", `/api/locations/${id}`, body),
  reorderLocations: (inventoryId: string, ids: string[]) =>
    request<ManagedLocation[]>("POST", `/api/inventories/${inventoryId}/locations/order`, { ids }),
  deleteLocation: (id: string) => request<void>("DELETE", `/api/locations/${id}`),
  locationShelfLife: (id: string) => request<LocationShelfLife>("GET", `/api/locations/${id}/shelf-life`),
  setShelfLife: (id: string, kind: "categories" | "foods", targetId: string, days: number | null) =>
    request<LocationShelfLife>(days === null ? "DELETE" : "PUT", `/api/locations/${id}/shelf-life/${kind}/${targetId}`, days === null ? undefined : { days }),
  notifications: () => request<NotificationSummary>("GET", "/api/notifications"),
  readNotifications: () => request<void>("POST", "/api/notifications/read-all"),

  preferences: () => request<Preferences>("GET", "/api/preferences"),
  updatePreferences: (body: Partial<Pick<Preferences, "diet" | "default_servings" | "expiring_soon_days">>) =>
    request<Preferences>("PATCH", "/api/preferences", body),
  setThreshold: (categoryId: string, days: number) => request<Preferences>("PUT", `/api/preferences/thresholds/${categoryId}`, { days }),
  removeThreshold: (categoryId: string) => request<Preferences>("DELETE", `/api/preferences/thresholds/${categoryId}`),
  setExclusion: (foodId: string, reason: "allergy" | "dislike") => request<Preferences>("PUT", `/api/preferences/exclusions/${foodId}`, { reason }),
  removeExclusion: (foodId: string) => request<Preferences>("DELETE", `/api/preferences/exclusions/${foodId}`),
  addBasic: (foodId: string) => request<Preferences>("PUT", `/api/preferences/basics/${foodId}`),
  removeBasic: (foodId: string) => request<Preferences>("DELETE", `/api/preferences/basics/${foodId}`),
  updateProfile: (display_name: string) => request<User>("PATCH", "/api/auth/me", { display_name }),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("POST", "/api/auth/password", { current_password, new_password }),
  deleteAccount: (password: string) => request<void>("DELETE", "/api/auth/me", { password }),

  dbStatus: () => request<DbStatus>("GET", "/api/admin/db-status"),
  checkDbNow: () => request<DbStatus>("POST", "/api/admin/check-now"),

  myRecipes: () => request<MyRecipes>("GET", "/api/my-recipes"),
  recipeForEdit: (id: string) => request<RecipeEdit>("GET", `/api/my-recipes/${id}`),
  createRecipe: (body: RecipeInput) => request<RecipeEdit>("POST", "/api/my-recipes", body),
  saveRecipe: (id: string, body: RecipeInput) => request<RecipeEdit>("PUT", `/api/my-recipes/${id}`, body),
  copyRecipe: (id: string) => request<RecipeEdit>("POST", `/api/my-recipes/${id}/copy`),
  deleteRecipe: (id: string) => request<void>("DELETE", `/api/my-recipes/${id}`),
  recipeShares: (id: string) => request<RecipeShareOut[]>("GET", `/api/my-recipes/${id}/shares`),
  shareRecipe: (id: string, body: { username?: string; inventory_id?: string }) =>
    request<RecipeShareOut[]>("POST", `/api/my-recipes/${id}/shares`, body),
  unshareRecipe: (id: string, shareId: string) => request<RecipeShareOut[]>("DELETE", `/api/my-recipes/${id}/shares/${shareId}`),

  utensils: () => request<Utensil[]>("GET", "/api/utensils"),
  setUtensilOwned: (id: string, owned: boolean) => request<Utensil>("PUT", `/api/utensils/${id}/owned`, { owned }),
  createUtensil: (name: string, category: Utensil["category"]) => request<Utensil>("POST", "/api/utensils", { name, category }),
  deleteUtensil: (id: string) => request<void>("DELETE", `/api/utensils/${id}`),
};
