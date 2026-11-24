// Appels à l'API FastAPI. Le cookie de session est envoyé automatiquement (même origine).

export type User = {
  id: string;
  username: string;
  display_name: string;
  role: "user" | "super_admin";
};

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

export type Difficulty = "easy" | "medium" | "hard";
export type Diet = "none" | "vegetarian" | "vegan";

/** Une recette : `id` est sa référence (id en base, adresse de la page sur un site, ou « ai:… »). */
export type RecipeCard = {
  id: string;
  recipe_id: string | null; // rempli si la recette est gardée en base
  title: string;
  source: "web" | "ai" | "user";
  site: string | null;
  site_label: string | null;
  status: "draft" | "complete";
  is_mine: boolean;
  image_url: string | null;
  external_url: string | null;
  base_servings: number;
  prep_minutes: number | null;
  cook_minutes: number | null;
  difficulty: Difficulty | null;
  is_vegan: boolean;
  is_vegetarian: boolean;
  health_score: number | null;
  site_rating: number | null;
  rating: number | null;
  comment: string | null;
  is_favorite: boolean;
  is_pinned: boolean;
  servings: number;
  wanted_found: string[]; // ingrédients cochés présents
  others: string[]; // autres ingrédients
  missing_utensils: string[];
  disliked: string[];
};

export type DailyRecipes = {
  day: string;
  recipes: { recipe: RecipeCard; origin: "web" | "base" | "ia" | "agent"; reasons: string[] }[];
};

export type RecipeDetail = RecipeCard & {
  ingredients: { id: string; name: string; raw_text: string; amount: string | null; wanted: boolean; disliked: boolean; optional: boolean }[];
  utensils: { name: string; owned: boolean; optional: boolean }[];
  steps: string[];
  nutrition: {
    per_serving?: Record<string, number | null>;
    points?: { label: string; points: number }[];
    serving_g?: number;
  } | null;
};

export type SearchQuery = {
  ingredients: string[];
  only: boolean;
  text?: string;
  servings?: number;
  diet?: Diet;
  difficulties: Difficulty[];
  max_minutes?: number;
  min_health?: number;
  max_health?: number;
  include_missing_utensils: boolean;
};

export type SearchResult = { recipes: RecipeCard[]; errors: string[] };

export type Term = { name: string; uses: number };

export type Utensil = { id: string; name: string; category: "cooking" | "preparation" | "container"; owned: boolean; is_custom: boolean };

export type MealSlot = "breakfast" | "lunch" | "snack" | "dinner";

export type Meal = {
  id: string;
  meal_date: string;
  slot: MealSlot;
  position: number;
  servings: number;
  recipe_id: string;
  title: string;
  image_url: string | null;
  agenda_id: string | null;
  agenda_name: string;
  planned_by: string | null;
  can_edit: boolean;
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

export type MealAlternative = { recipe: RecipeCard; reasons: string[] };

export type MealDraft = { meal_date: string; slot: MealSlot; recipe: RecipeCard | null; reasons: string[] };

export type SuggestBody = { days: string[]; slots?: MealSlot[]; agenda: string; servings?: number; exclude?: string[] };

export type MealCreate = {
  recipe_ref: string;
  meal_date: string;
  slot: MealSlot;
  servings: number;
  shared_agenda_id?: string;
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
  freeze_from: string | null;
};

export type ShoppingList = { id: string; name: string; lines: ShoppingLine[] };

export type Role = "admin" | "contributor" | "member";

export type Agenda = { id: string; name: string; my_role: Role };

export type AgendaDetail = Agenda & {
  members: { user_id: string; username: string; display_name: string; role: Role; is_me: boolean }[];
  invitations: { id: string; username: string; display_name: string }[];
};

export type MyInvitation = { id: string; agenda_id: string; agenda_name: string; invited_by: string | null; created_at: string };

export type NotificationSummary = {
  unread: number;
  pending_invitations: number;
  items: { id: string; type: string; message: string; created_at: string; read: boolean }[];
};

export type Preferences = {
  diet: Diet;
  default_servings: number;
  exclusions: { food_id: string; name: string; reason: "allergy" | "dislike" }[];
  tolerated_ingredients: string[];
  default_tolerated_ingredients: string[];
};

export type PhotoIngredients = { ingredients: { name: string; sure: boolean }[]; engine: "claude" | "local"; fallback: boolean };

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
  difficulty: Difficulty | null;
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

export type RecipeShareOut = { id: string; label: string; kind: "user" | "agenda" };

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

  warmUpPhotoModel: () => request<{ engine: "claude" | "local"; warming: boolean }>("POST", "/api/photo/warm-up"),
  photoIngredients: (photos: { media_type: string; data: string }[]) =>
    request<PhotoIngredients>("POST", "/api/photo/ingredients", { photos }),
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

  ingredients: (q = "", limit = 30) => request<Term[]>("GET", `/api/ingredients?${query({ q, limit })}`),
  searchRecipes: (body: SearchQuery) => request<SearchResult>("POST", "/api/recipes/search", body),
  favorites: () => request<RecipeCard[]>("GET", "/api/recipes/favorites"),
  dailyRecipes: () => request<DailyRecipes>("GET", "/api/recipes/daily"),
  recipe: (ref: string, servings?: number, ingredients?: string[]) =>
    request<RecipeDetail>("GET", `/api/recipes/view?${query({ ref, servings, ingredients })}`),
  updateMeta: (ref: string, body: MetaUpdate) => request<RecipeCard>("PUT", `/api/recipes/meta?${query({ ref })}`, body),
  importRecipe: (url: string) => request<RecipeCard>("POST", "/api/recipes/import", { url }),
  generateRecipes: (body: { count: number; servings: number; diet: Diet; ingredients: string[]; only: boolean; wish?: string }) =>
    request<RecipeCard[]>("POST", "/api/recipes/generate", body),

  agenda: (start: string, end: string) => request<Meal[]>("GET", `/api/agenda?${query({ start, end })}`),
  weekBalance: (start: string, agenda: string) => request<WeekBalance>("GET", `/api/agenda/balance?${query({ start, agenda })}`),
  mealAlternatives: (id: string, focus?: string) => request<MealAlternative[]>("GET", `/api/agenda/${id}/alternatives?${query({ focus })}`),
  replaceMeal: (id: string, recipe_ref: string) => request<Meal>("POST", `/api/agenda/${id}/replace`, { recipe_ref }),
  suggestMeals: (body: SuggestBody) => request<MealDraft[]>("POST", "/api/agenda/suggest", body),
  planMeal: (body: MealCreate) => request<Meal>("POST", "/api/agenda", body),
  updateMeal: (id: string, body: MealChange) => request<Meal>("PATCH", `/api/agenda/${id}`, body),
  removeMeal: (id: string) => request<void>("DELETE", `/api/agenda/${id}`),

  shopping: () => request<ShoppingList[]>("GET", "/api/shopping"),
  addShoppingLine: (label: string, shared_agenda_id?: string) =>
    request<ShoppingLine>("POST", "/api/shopping/manual", { label, shared_agenda_id }),
  deleteShoppingLine: (id: string) => request<void>("DELETE", `/api/shopping/${id}`),
  purchase: (ids: string[]) => request<{ removed_from_list: number }>("POST", "/api/shopping/purchase", { ids }),

  agendas: () => request<Agenda[]>("GET", "/api/agendas"),
  createAgenda: (name: string) => request<AgendaDetail>("POST", "/api/agendas", { name }),
  agendaDetail: (id: string) => request<AgendaDetail>("GET", `/api/agendas/${id}`),
  renameAgenda: (id: string, name: string) => request<AgendaDetail>("PATCH", `/api/agendas/${id}`, { name }),
  deleteAgenda: (id: string) => request<void>("DELETE", `/api/agendas/${id}`),
  invite: (id: string, username: string) => request<AgendaDetail>("POST", `/api/agendas/${id}/invitations`, { username }),
  cancelInvitation: (id: string, invitationId: string) => request<void>("DELETE", `/api/agendas/${id}/invitations/${invitationId}`),
  changeRole: (id: string, userId: string, role: Role) => request<AgendaDetail>("PATCH", `/api/agendas/${id}/members/${userId}`, { role }),
  removeMember: (id: string, userId: string) => request<void>("DELETE", `/api/agendas/${id}/members/${userId}`),
  myInvitations: () => request<MyInvitation[]>("GET", "/api/invitations"),
  acceptInvitation: (id: string) => request<AgendaDetail>("POST", `/api/invitations/${id}/accept`),
  declineInvitation: (id: string) => request<void>("POST", `/api/invitations/${id}/decline`),
  notifications: () => request<NotificationSummary>("GET", "/api/notifications"),
  readNotifications: () => request<void>("POST", "/api/notifications/read-all"),

  preferences: () => request<Preferences>("GET", "/api/preferences"),
  updatePreferences: (body: Partial<Pick<Preferences, "diet" | "default_servings" | "tolerated_ingredients">>) =>
    request<Preferences>("PATCH", "/api/preferences", body),
  setExclusion: (foodId: string, reason: "allergy" | "dislike") => request<Preferences>("PUT", `/api/preferences/exclusions/${foodId}`, { reason }),
  removeExclusion: (foodId: string) => request<Preferences>("DELETE", `/api/preferences/exclusions/${foodId}`),
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
  copyRecipe: (ref: string) => request<RecipeEdit>("POST", `/api/my-recipes/copy?${query({ ref })}`),
  deleteRecipe: (id: string) => request<void>("DELETE", `/api/my-recipes/${id}`),
  recipeShares: (id: string) => request<RecipeShareOut[]>("GET", `/api/my-recipes/${id}/shares`),
  shareRecipe: (id: string, body: { username?: string; agenda_id?: string }) =>
    request<RecipeShareOut[]>("POST", `/api/my-recipes/${id}/shares`, body),
  unshareRecipe: (id: string, shareId: string) => request<RecipeShareOut[]>("DELETE", `/api/my-recipes/${id}/shares/${shareId}`),

  utensils: () => request<Utensil[]>("GET", "/api/utensils"),
  setUtensilOwned: (id: string, owned: boolean) => request<Utensil>("PUT", `/api/utensils/${id}/owned`, { owned }),
  createUtensil: (name: string, category: Utensil["category"]) => request<Utensil>("POST", "/api/utensils", { name, category }),
  deleteUtensil: (id: string) => request<void>("DELETE", `/api/utensils/${id}`),
};
