# Secrets

Chaque secret est un fichier texte de ce dossier, sans extension, contenant
uniquement la valeur. Ces fichiers ne sont jamais versionnés (voir `.gitignore`)
et Docker les monte dans le conteneur sous `/run/secrets/<nom>`.

| Fichier | Contenu | Utilisé à partir de |
| --- | --- | --- |
| `database_url` | URL de connexion PostgreSQL Supabase (`postgresql://...`) | Maintenant |
| `anthropic_api_key` | Clé d'API Claude | Étape photo |
| `smtp_sender`, `smtp_password`, `admin_email` | Compte Gmail d'envoi et adresse du super-administrateur | Surveillance de la base |
| `status_page_key` | Clé de la page de statut | Surveillance de la base |

Un fichier vide équivaut à un secret absent : l'application démarre quand même
et le signale (par exemple « base de données non configurée »).
