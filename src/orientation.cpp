#include <math.h>
#include <config.h>
#include <imu.cpp>
#include <baro.cpp>
#include <vector.h>

IMU imu;
float scaleAccZ = 1.0f;

struct quaternion {
    float w;
    float x;
    float y;
    float z;
};

quaternion q;

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
    float yaw = 0.0f;

    float halfRoll = roll * 0.5f;
    float halfPitch = pitch * 0.5f;
    float halfYaw = yaw * 0.5f;

    float cosRoll = cosf(halfRoll);
    float sinRoll = sinf(halfRoll);

    float cosPitch = cosf(halfPitch);
    float sinPitch = sinf(halfPitch);

    float cosYaw = cosf(halfYaw);
    float sinYaw = sinf(halfYaw);

    q.w = cosRoll * cosPitch * cosYaw + sinRoll * sinPitch * sinYaw;
    q.x = sinRoll * cosPitch * cosYaw - cosRoll * sinPitch * sinYaw;
    q.y = cosRoll * sinPitch * cosYaw + sinRoll * cosPitch * sinYaw;
    q.z = cosRoll * cosPitch * sinYaw - sinRoll * sinPitch * cosYaw;
}