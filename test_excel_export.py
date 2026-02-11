import pandas as pd
import io

try:
    print("Testing pandas Excel export...")
    df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    print("✅ Excel export successful!")
except Exception as e:
    print(f"❌ Excel export failed: {e}")
    import traceback
    traceback.print_exc()
