"""Coût des appels à l'IA, enregistré à chaque appel pour le suivi du super-administrateur.

Le coût est estimé à partir des jetons renvoyés par l'API et des tarifs publics (dollars par
million de jetons). Le modèle facturé est celui qui a répondu : en cas de repli après un refus,
ce peut être un autre que celui demandé. Le modèle local (Ollama) est gratuit : compté à 0.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import AiUsage, User

# (entrée, sortie) en dollars par million de jetons
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    # modèles de repli possibles
    "claude-opus-5": (Decimal("5"), Decimal("25")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25")),
    "claude-sonnet-5": (Decimal("2"), Decimal("10")),
}
UNKNOWN_PRICE = (Decimal("5"), Decimal("25"))  # modèle inconnu : estimation prudente
MILLION = Decimal(1_000_000)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    if model.startswith("local:"):
        return Decimal(0)
    price_in, price_out = PRICES.get(model, UNKNOWN_PRICE)
    return (price_in * input_tokens + price_out * output_tokens) / MILLION


def record(session: Session, user: User, kind: str, model: str, input_tokens: int, output_tokens: int) -> AiUsage:
    usage = AiUsage(user_id=user.id, username=user.username, kind=kind, model=model,
                    input_tokens=int(input_tokens or 0), output_tokens=int(output_tokens or 0),
                    cost_usd=cost_usd(model, input_tokens or 0, output_tokens or 0).quantize(Decimal("0.000001")))
    session.add(usage)
    return usage


def recorder(session: Session, user: User, kind: str):
    """Fonction à passer aux moteurs IA : appelée avec (modèle, jetons entrée, jetons sortie) après chaque réponse."""
    return lambda model, input_tokens, output_tokens: record(session, user, kind, model, input_tokens, output_tokens)


AI_DAILY_CALLS = 8  # inventions de recettes par l'IA, par utilisateur et par jour (chacune coûte quelques centimes)


def ai_calls_today(session: Session, user: User) -> int:
    from datetime import datetime

    from sqlalchemy import func, select

    from app.clock import APP_TIMEZONE, today

    start = datetime.combine(today(), datetime.min.time(), tzinfo=APP_TIMEZONE)
    return session.scalar(select(func.count()).select_from(AiUsage).where(
        AiUsage.user_id == user.id, AiUsage.kind == "recipe", AiUsage.created_at >= start)) or 0
