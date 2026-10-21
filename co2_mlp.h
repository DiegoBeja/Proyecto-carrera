// co2_mlp.h - Estima CO2 con el MLP de modelo_co2.h a partir de promedios de 1 minuto.
//
// Calcula las mismas entradas que merge.py + entrenar.py (sin presion, ventana de 5 min):
//   log1p de conteos y de pm1_est/pm2_5_est, temp, HR, humedad absoluta, log10(gas),
//   promedio movil de 5 min (incluye el minuto actual) y tendencia (valor - valor de hace 5 min).
// No depende de Arduino: tambien compila en la PC para comprobar que da lo mismo que Python.
#pragma once
#include <math.h>
#include "modelo_co2.h"

struct MinutoCO2 {
  double n[6];   // conteos promedio del minuto: n0_3, n0_5, n1_0, n2_5, n5_0, n10 (por 0.1 L)
  double tempC, rh, gasOhm;   // promedios del minuto del BME688
};

inline double humedadAbsoluta(double tC, double rh) {   // g/m3 (igual que merge.py)
  return 6.112 * exp(17.67 * tC / (tC + 243.5)) * rh * 2.1674 / (273.15 + tC);
}

// Corre las MLP_REDES redes y promedia; x ya en el orden de entradas (sin escalar)
inline double mlpPredecir(const float* x) {
  float xs[MLP_ENTRADAS];
  for (int i = 0; i < MLP_ENTRADAS; i++) xs[i] = (x[i] - MLP_X_MEDIA[i]) / MLP_X_ESCALA[i];
  double suma = 0;
  for (int r = 0; r < MLP_REDES; r++) {
    const float* w1 = MLP_W1 + r * MLP_ENTRADAS * MLP_OCULTA;
    double salida = MLP_B2[r];
    for (int j = 0; j < MLP_OCULTA; j++) {
      double z = MLP_B1[r * MLP_OCULTA + j];
      for (int i = 0; i < MLP_ENTRADAS; i++) z += xs[i] * w1[i * MLP_OCULTA + j];
      salida += tanh(z) * MLP_W2[r * MLP_OCULTA + j];
    }
    suma += salida;
  }
  return suma / MLP_REDES * MLP_Y_ESCALA + MLP_Y_MEDIA;
}

class EstimadorCO2 {
 public:
  float x[MLP_ENTRADAS];   // entradas del ultimo minuto (para depurar)
  int fueraDeRango = 0;    // cuantas entradas quedaron fuera del rango de entrenamiento

  // Agrega un minuto y devuelve el CO2 estimado (ppm)
  double agregarMinuto(const MinutoCO2& m) {
    const double rho = 1.65;   // densidad supuesta en merge.py (--pm-density)
    auto coef = [&](double d) { return M_PI / 6 * d * d * d * rho * 1e-2; };
    double pm1 = (m.n[0] - m.n[1]) * coef(0.3873) + (m.n[1] - m.n[2]) * coef(0.7071);
    double pm25 = pm1 + (m.n[2] - m.n[3]) * coef(1.5811);
    double ah = humedadAbsoluta(m.tempC, m.rh);
    double lgas = log10(m.gasOhm);

    for (int i = 0; i < 6; i++) x[i] = log1p(m.n[i]);
    x[6] = log1p(pm1);
    x[7] = log1p(pm25);
    x[8] = m.tempC;
    x[9] = m.rh;
    x[10] = ah;
    x[11] = lgas;

    // historial de las 4 senales dinamicas: log10_gas, abs_hum, temp, log_n0_3
    double actual[4] = { lgas, ah, m.tempC, x[0] };
    for (int k = 0; k < 4; k++) {
      for (int i = MLP_VENTANA; i > 0; i--) hist[k][i] = hist[k][i - 1];
      hist[k][0] = actual[k];
    }
    if (n < MLP_VENTANA + 1) n++;
    int enMedia = n < MLP_VENTANA ? n : MLP_VENTANA;
    for (int k = 0; k < 4; k++) {
      double s = 0;
      for (int i = 0; i < enMedia; i++) s += hist[k][i];
      x[12 + k] = s / enMedia;                                          // _m5
      x[16 + k] = n > MLP_VENTANA ? hist[k][0] - hist[k][MLP_VENTANA] : 0;  // _d5 (0 los primeros 5 min)
    }

    fueraDeRango = 0;
    for (int i = 0; i < MLP_ENTRADAS; i++)
      if (x[i] < MLP_X_MIN[i] || x[i] > MLP_X_MAX[i]) fueraDeRango++;
    return mlpPredecir(x);
  }

  int minutos() const { return n; }

 private:
  double hist[4][MLP_VENTANA + 1] = {};
  int n = 0;
};
