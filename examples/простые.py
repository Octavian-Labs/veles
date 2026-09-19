# простые — эталонный бенчмарк на Python: та же логика, что в простые.раз.
# Перебор делителей до sqrt(n) — чистая арифметика, без ввода-вывода в цикле.


def простое(n):
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    д = 3
    while д * д <= n:
        if n % д == 0:
            return False
        д += 2
    return True


def главная():
    N = 2000000
    к = 0
    for i in range(2, N + 1):
        if простое(i):
            к += 1
    print(f"простых до {N}: {к}")
    return 0


if __name__ == "__main__":
    главная()
