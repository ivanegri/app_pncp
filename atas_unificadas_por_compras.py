import pandas as pd

df = pd.read_csv("CSVs/atas_2026_full.csv")
df_compras = df.drop_duplicates(subset=['numeroControlePNCPCompra'], keep='first')

print(df_compras.head())    

df_compras.to_csv("compras_2026_unificadas.csv", index=False)