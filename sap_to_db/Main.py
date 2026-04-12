from node_parser import NodeParser
from db_writer import MySQLWriter

if __name__ == "__main__":
    s2k_path = "./Source/Z30103A6.s2k"

    parser = NodeParser(s2k_path)
    node_df = parser.dataframe()

    print(node_df.head())

    writer = MySQLWriter(
        user="root",
        password="pqh2002P",
        host="127.0.0.1",
        port=3306,
        database="ttowertest"
    )

    writer.write_dataframe(node_df, "节点表", if_exists="append")
    print("node表写入完成")


