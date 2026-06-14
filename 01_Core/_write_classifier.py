import base64, os

# Leer las 4 partes del b64 desde outputs
base = r"C:\Users\Pc\Desktop\PROYECTOS\WALLAPOP"
out = r"C:\Users\Pc\Downloads"  # directorio de descarga donde Claude las pone

# Las partes las leemos desde el directorio de outputs del sandbox
# que Desktop Commander puede acceder como outputs de Claude
import sys

def read_part(n):
    # intentar desde varios sitios posibles
    for path in [
        rf"C:\Users\Pc\Downloads\b64_p{n}.txt",
        rf"C:\Users\Pc\Desktop\b64_p{n}.txt",
    ]:
        if os.path.exists(path):
            return open(path).read().strip()
    return None

parts = [read_part(i) for i in range(4)]
missing = [i for i, p in enumerate(parts) if p is None]
if missing:
    print(f"Faltan partes: {missing}")
    sys.exit(1)

data = base64.b64decode("".join(parts))
dest = rf"{base}\01_Core\classifier.py"
with open(dest, "wb") as f:
    f.write(data)
print(f"escrito {len(data)} bytes en {dest}")

import py_compile
py_compile.compile(dest, doraise=True)
print("sintaxis OK")
