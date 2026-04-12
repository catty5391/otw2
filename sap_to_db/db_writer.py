from sqlalchemy import create_engine

class MySQLWriter:
    def __init__(self, user, password, host, port, database):
        self.engine = create_engine(
            f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"
        )

    def write_dataframe(self, df, table_name, if_exists="append"):
        df.to_sql(
            name=table_name,
            con=self.engine,
            if_exists=if_exists,
            index=False
        )