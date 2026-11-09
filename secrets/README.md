# Secrets

Chaque secret est un fichier texte de ce dossier, sans extension, contenant
uniquement la valeur. Ces fichiers ne sont jamais versionnés (voir `.gitignore`)
et Docker les monte dans le conteneur sous `/run/secrets/<nom>`.

| Fichier | Contenu | Utilisé à partir de |
| --- | --- | --- |
| `database_url` | URL de connexion PostgreSQL Supabase (`postgresql://...`) | Maintenant |
| `anthropic_api_key` | Clé d'API Claude (console.anthropic.com → API Keys), pour les recettes IA puis l'analyse photo | Maintenant |
| `smtp_sender` | Adresse Gmail qui envoie les alertes | Maintenant |
| `smtp_password` | Mot de passe d'application de ce compte Gmail (16 lettres, espaces acceptés) | Maintenant |
| `admin_email` | Adresse du super-administrateur qui reçoit les alertes | Maintenant |
| `status_page_key` | Clé longue et aléatoire pour la page de statut (vide = page désactivée) | Maintenant |

Docker Compose exige que chaque fichier existe, même vide. Après les avoir remplis :
`docker compose up -d --force-recreate`, puis `docker compose exec app python -m app.cli test-email`.

Un fichier vide équivaut à un secret absent : l'application démarre quand même
et le signale (par exemple « base de données non configurée »).
