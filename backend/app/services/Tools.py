import os
import pandas as pd

def es_numero_bancario(s):
    if s is None:
        return False
    s = str(s).strip()
    s2 = s.replace('.', '').replace(',', '').replace('-', '').replace('$', '').replace(' ', '')
    return s2.lstrip('-+').isdigit()

def limpiar_numero(s):
    if s is None:
        return 0.0
    s = str(s).strip()
    s = s.replace('$', '').replace(' ', '')
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        import re
        s2 = re.sub(r'[^\\d\\.\\-]', '', s)
        try:
            return float(s2) if s2 not in ('', '-', '.', '-.') else 0.0
        except Exception:
            return 0.0

def guardar_excel(df, excel_path):
    try:
        os.makedirs(os.path.dirname(excel_path) or '.', exist_ok=True)
        df.to_excel(excel_path, index=False)
        return True, excel_path
    except Exception as e:
        return False, str(e)

class TrackerSaldo:
    def __init__(self):
        self.saldo = 0.0
