#include <math.h>
#include <config.h>
#include <imu.cpp>
#include <baro.cpp>
#include <vector.h>

IMU imu;
float scaleAccZ = 1.0f;

void initOrientation() {
    float a[3];
    a[0] = imu.getAccX();
    a[1] = imu.getAccY();
    a[2] = imu.getAccZ();

    a[2] *= scaleAccZ;

    if (a[2] == 0.0f) {
        a[2] = 0.00001f; // prevent indivisible
    }

    float tmp[3];
    copyVector(tmp, a);
    normalizeVector(tmp);



}