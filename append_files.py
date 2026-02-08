import pandas as pd
import os

# Diretório onde estão os arquivos CSV
directory = 'data/atas_2025'

# Lista para armazenar os DataFrames
df_list = []

# Itera sobre todos os arquivos no diretório
for filename in os.listdir(directory):
    if filename.endswith('.csv'):
        file_path = os.path.join(directory, filename)
        print(f'Lendo arquivo: {file_path}')
        
        # Lê o CSV e adiciona à lista
        df = pd.read_csv(file_path)
        df_list.append(df)

# Concatena todos os DataFrames
if df_list:
    final_df = pd.concat(df_list, ignore_index=True)
    #final_df.drop_duplicates(subset=['cnpj'], keep='first', inplace=True)
    
    # Salva o DataFrame resultante em um novo CSV
    output_file = 'atas_2025_full.csv'
    final_df.to_csv(output_file, index=False)
    print(f'\nArquivo final salvo como: {output_file}')
    print(f'Total de linhas: {len(final_df)}')
else:
    print('Nenhum arquivo CSV encontrado.')