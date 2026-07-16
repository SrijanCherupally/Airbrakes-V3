/*

#include <math.h>
#include <orientation.cpp>
#include "kalman.h"
#include "config.h"
#include "coast_table.h"

Kalman filter(0.01f);
float MotorOffset;

float currentCd(float acceleration, float velocity) {

    float dragForce = MASS * (-acceleration - G);
    float currentCd = 2 * dragForce / (RHO * AREA * velocity * velocity);
    return currentCd;

}

static float solveDesiredCdContinuous(float velocity, float altitude) {
  float predMinCd = altitude + getCoastAltitude(velocity, COAST_CD_MIN);
  float predMaxCd = altitude + getCoastAltitude(velocity, COAST_CD_MAX);

  // Target above no-brake prediction => close brakes.
  if (TARGET_ALTITUDE >= predMinCd) {
    return COAST_CD_MIN;
  }
  // Target below max-brake prediction => full brakes.
  if (TARGET_ALTITUDE <= predMaxCd) {
    return COAST_CD_MAX;
  }

  // Coast altitude is monotonic with Cd, so bisection gives a smooth Cd.
  float lo = COAST_CD_MIN;
  float hi = COAST_CD_MAX;
  for (int i = 0; i < 14; ++i) {
    float mid = 0.5f * (lo + hi);
    float pred = altitude + getCoastAltitude(velocity, mid);
    if (pred > TARGET_ALTITUDE) {
      lo = mid;  // Need more drag
    } else {
      hi = mid;  // Need less drag
    }
  }
  return 0.5f * (lo + hi);
}

float getCoastAltitude(float velocity, float cd) {
  // Clamp inputs
  if (velocity < COAST_VEL_MIN) velocity = COAST_VEL_MIN;
  if (velocity > COAST_VEL_MAX) velocity = COAST_VEL_MAX;
  if (cd < COAST_CD_MIN) cd = COAST_CD_MIN;
  if (cd > COAST_CD_MAX) cd = COAST_CD_MAX;

  // Find lower indices
  int vi = (int)((velocity - COAST_VEL_MIN) / COAST_VEL_STEP);
  int ci = (int)((cd - COAST_CD_MIN) / COAST_CD_STEP);
  if (vi > COAST_N_VEL - 2) vi = COAST_N_VEL - 2;
  if (ci > COAST_N_CD - 2) ci = COAST_N_CD - 2;

  // Bilinear interpolation weights
  float vw =
      (velocity - (COAST_VEL_MIN + vi * COAST_VEL_STEP)) / COAST_VEL_STEP;
  float cw = (cd - (COAST_CD_MIN + ci * COAST_CD_STEP)) / COAST_CD_STEP;

  float a00 = COAST_ALTITUDE_TABLE[vi][ci];
  float a01 = COAST_ALTITUDE_TABLE[vi][ci + 1];
  float a10 = COAST_ALTITUDE_TABLE[vi + 1][ci];
  float a11 = COAST_ALTITUDE_TABLE[vi + 1][ci + 1];

  float a0 = a00 * (1.0f - vw) + a10 * vw;
  float a1 = a01 * (1.0f - vw) + a11 * vw;
  return a0 * (1.0f - cw) + a1 * cw;
}

*/
