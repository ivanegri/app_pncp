import pandas as pd

df = pd.read_csv("atas_2025_full.csv")
df_compras = df.drop_duplicates(subset=['numeroControlePNCPCompra'], keep='first')

print(df_compras.head())    

df_compras.to_csv("compras_2025_unificadas.csv", index=False)