# DCO - Dev Cost Optimizer

## Инициализация
- PSQL DB: [init_db.sh](init_db.sh)
- PSQL TABLES: [CORE_INIT.sql](CORE_INIT.sql)

## Start
```python3.13 -m uvicorn src.api.main:app --reload```

## Migrations
```rm alembic/versions/#######_init.py```  
```alembic revision --autogenerate -m "init"```  
```alembic upgrade head```
