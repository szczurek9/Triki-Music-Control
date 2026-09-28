import asyncio
import ctypes
import math
import time
from collections import deque

from TrikiPy import TrikiDevice


# =========================
# KONFIGURACJA
# =========================

# Prędkość obrotu wokół osi kapsla potrzebna do wykrycia skrętu.
ROTATION_THRESHOLD = 2050

# Minimalny czas między kolejnymi skipami.
SKIP_COOLDOWN = 0.9

# Po ilu jednostkach ruchu uznajemy, że kapsel przestał się obracać.
ROTATION_RESET_THRESHOLD = 180

# Potrząśnięcie.
SHAKE_THRESHOLD = 18000
SHAKE_COOLDOWN = 0.60
SHAKE_WINDOW = 4

# Jeżeli kierunek okaże się odwrotny, zmień na -1.
ROTATION_DIRECTION = -1


# =========================
# WINDOWS MEDIA KEYS
# =========================

user32 = ctypes.windll.user32

VK_MEDIA_NEXT = 0xB0
VK_MEDIA_PREV = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

KEYEVENTF_KEYUP = 0x0002


def press_key(vk):
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def next_track():
    press_key(VK_MEDIA_NEXT)
    print("  >> następny utwór")


def previous_track():
    press_key(VK_MEDIA_PREV)
    print("  << poprzedni utwór")


def play_pause():
    press_key(VK_MEDIA_PLAY_PAUSE)
    print("  ||/> play/pause")


def magnitude(x, y, z):
    return math.sqrt(x * x + y * y + z * z)


class GestureState:
    def __init__(self):
        self.last_skip = 0.0
        self.last_shake = 0.0

        # Zapobiega wielokrotnemu wyzwalaniu podczas jednego obrotu.
        self.rotation_armed = True

        self.shake_values = deque(maxlen=SHAKE_WINDOW)

        # Wolnozmienny wektor grawitacji.
        self.gravity = [0.0, 0.0, 0.0]
        self.gravity_initialized = False

    def update_gravity(self, ax, ay, az):
        # Niewielki filtr LPF: zachowuje kierunek grawitacji,
        # ale usuwa większość krótkich impulsów.
        alpha = 0.08

        if not self.gravity_initialized:
            self.gravity[:] = [ax, ay, az]
            self.gravity_initialized = True
            return

        self.gravity[0] += alpha * (ax - self.gravity[0])
        self.gravity[1] += alpha * (ay - self.gravity[1])
        self.gravity[2] += alpha * (az - self.gravity[2])

    def get_twist_speed(self, gx, gy, gz):
        """
        Zamiast używać na sztywno gz, liczymy składową żyroskopu
        wzdłuż osi grawitacji.

        Dzięki temu:
          - obrót kapsla jak pokrętłem = twist,
          - nie ma znaczenia, jak kapsel jest obrócony w dłoni,
          - przypadkowe gx/gy nie będą powodowały "poprzedni".
        """
        gx0, gy0, gz0 = self.gravity
        g_len = magnitude(gx0, gy0, gz0)

        if g_len < 300:
            return 0.0

        nx = gx0 / g_len
        ny = gy0 / g_len
        nz = gz0 / g_len

        # Rzut wektora prędkości kątowej na oś grawitacji.
        twist = gx * nx + gy * ny + gz * nz

        return twist * ROTATION_DIRECTION

    def handle_rotation(self, gx, gy, gz, now):
        twist = self.get_twist_speed(gx, gy, gz)

        if self.rotation_armed and abs(twist) >= ROTATION_THRESHOLD:
            if now - self.last_skip >= SKIP_COOLDOWN:
                self.last_skip = now
                self.rotation_armed = False

                if twist > 0:
                    next_track()
                else:
                    previous_track()

        # Uzbrojenie ponownie dopiero po uspokojeniu obrotu.
        if not self.rotation_armed and abs(twist) <= ROTATION_RESET_THRESHOLD:
            self.rotation_armed = True

    def handle_shake(self, ax, ay, az, now):
        self.update_gravity(ax, ay, az)

        # Odjęcie grawitacji zostawia dynamiczne przyspieszenie,
        # czyli to, czego szukamy przy potrząśnięciu.
        dynamic = magnitude(
            ax - self.gravity[0],
            ay - self.gravity[1],
            az - self.gravity[2],
        )

        self.shake_values.append(dynamic)

        if (
            max(self.shake_values, default=0) >= SHAKE_THRESHOLD
            and now - self.last_shake >= SHAKE_COOLDOWN
        ):
            self.last_shake = now
            self.shake_values.clear()
            play_pause()


async def main():
    print("=" * 50)
    print("TRIKI MUSIC CONTROLLER")
    print("=" * 50)
    print("Szukam kapsla przez Bluetooth...")

    triki = TrikiDevice(BTName="Triki", literal=False)

    if not await triki.connectTriki():
        print("Nie udało się połączyć z Triki.")
        return

    print(f"Połączono: {triki.getName()}")

    battery = await triki.getBatteryLevel()
    if battery >= 0:
        print(f"Bateria: {battery}%")

    if not await triki.startTriki():
        print("Nie udało się uruchomić IMU.")
        await triki.stopTriki()
        return

    print()
    print("Gotowe!")
    print(" OBRÓT W PRAWO = następny")
    print(" OBRÓT W LEWO  = poprzedni")
    print(" POTRZĄŚNIĘCIE = play/pause")
    print(" Ctrl+C        = wyjście")
    print()

    state = GestureState()

    try:
        while True:
            data = await triki.getTrikiData()
            now = time.monotonic()

            # Najpierw aktualizujemy grawitację.
            state.update_gravity(data.ax, data.ay, data.az)

            state.handle_rotation(
                data.gx,
                data.gy,
                data.gz,
                now,
            )

            state.handle_shake(
                data.ax,
                data.ay,
                data.az,
                now,
            )

    except KeyboardInterrupt:
        print("\nZamykanie...")

    finally:
        await triki.stopTriki()
        print("Odłączono Triki.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
