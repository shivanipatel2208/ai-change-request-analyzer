# models/

SQLAlchemy ORM models, one file per table. All registered via `__init__.py`
so `Base.metadata.create_all()` (see `app/database/init_db.py`) picks them
all up.

Tables: `users`, `change_requests`, `analyses`, `requirements`,
`affected_components`, `dependencies`, `risks`, `clarification_questions`,
`test_cases`, `implementation_tasks`. Shared enums live in `enums.py`.
