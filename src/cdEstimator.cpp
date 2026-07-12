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
        a[2] = 0.00001f; // prevent indivisiblity
    }

    float tmp[3];
    copyVector(tmp, a);
    normalizeVector(tmp);

    float roll = atan2f(tmp[1], tmp[2]);
    float pitch = -asinf(tmp[0]);

    float cosRoll = cosf(roll);
    float sinRoll = sinf(roll);

    float cosPitch = cosf(pitch);
    float sinPitch = sinf(pitch);       

    float yaw = 0.0f;
    float cosYaw = cosf(yaw);
    float sinYaw = sinf(yaw);

    float C[3][3];

    C[0][0] = cosPitch * cosYaw;
    C[0][1] = sinRoll * sinPitch * cosYaw - cosRoll * sinYaw;
    C[0][2] = cosRoll * sinPitch * cosYaw + sinRoll * sinYaw;

    C[1][0] = cosPitch * sinYaw;
    C[1][1] = sinRoll * sinPitch * sinYaw + cosRoll * cosYaw;
    C[1][2] = cosRoll * sinPitch * sinYaw - sinRoll * cosYaw;

    C[2][0] = -sinPitch;
    C[2][1] = sinRoll * cosPitch;
    C[2][2] = cosRoll * cosPitch;

}