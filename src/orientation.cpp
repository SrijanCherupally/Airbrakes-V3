#include <math.h>
#include <config.h>
#include <imu.cpp>
#include <vector.h>

#define loopTime 500 // Hz
const float dT = 1.0f / (float)loopTime;

IMU imu;
float scaleAccZ = 1.0f;

struct quaternion {
    float w;
    float x;
    float y;
    float z;
};

quaternion q = {1.0f, 0.0f, 0.0f, 0.0f};

void initOrientation() {

    float accel[3];
    accel[0] = imu.getAccX();
    accel[1] = imu.getAccY();
    accel[2] = imu.getAccZ();

    accel[2] *= scaleAccZ;

    if (accel[2] == 0.0f) {
        accel[2] = 0.00001f; // prevent indivisiblity
    }

    float tmp[3];
    copyVector(tmp, accel);
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

void multiplyQuaternion(const quaternion &a,
                        const quaternion &b,
                        quaternion &result)
{
    result.w = a.w*b.w - a.x*b.x - a.y*b.y - a.z*b.z;

    result.x = a.w*b.x + a.x*b.w + a.y*b.z - a.z*b.y;

    result.y = a.w*b.y - a.x*b.z + a.y*b.w + a.z*b.x;

    result.z = a.w*b.z + a.x*b.y - a.y*b.x + a.z*b.w;
}

void updateOrientation() {

    quaternion dq;

    float gyro[3];
    gyro[0] = imu.getGyrX();
    gyro[1] = imu.getGyrY();
    gyro[2] = imu.getGyrZ();

    float deltaRot[3];
    copyVector(deltaRot, gyro);

    deltaRot[0] *= dT;
    deltaRot[1] *= dT;
    deltaRot[2] *= dT;

    float theta = sqrtf(deltaRot[0] * deltaRot[0] + deltaRot[1] * deltaRot[1] + deltaRot[2] * deltaRot[2]);

    float rotAxis[3];
    copyVector(rotAxis, deltaRot);

    if (theta < 1e-6f) 
    {
        dq.w = 1.0f;
        dq.x = 0.0f;
        dq.y = 0.0f;
        dq.z = 0.0f;
    }
    else
    {
        rotAxis[0] /= theta;
        rotAxis[1] /= theta;
        rotAxis[2] /= theta;

        float halfTheta = theta * 0.5f;
        float sinHalfTheta = sinf(halfTheta);

        dq.w = cosf(halfTheta);
        dq.x = rotAxis[0] * sinHalfTheta;
        dq.y = rotAxis[1] * sinHalfTheta;
        dq.z = rotAxis[2] * sinHalfTheta;
    }

    quaternion result;

    multiplyQuaternion(q, dq, result);

    q = result;

    float mag = sqrtf(q.w*q.w + q.x*q.x + q.y*q.y + q.z*q.z);

    q.w /= mag;
    q.x /= mag;
    q.y /= mag;
    q.z /= mag;

}

void quaternionToMatrix(float R[3][3])
{
    R[0][0] = 1.0f - 2.0f * (q.y * q.y + q.z * q.z);
    R[0][1] = 2.0f * (q.x * q.y - q.z * q.w);
    R[0][2] = 2.0f * (q.x * q.z + q.y * q.w);

    R[1][0] = 2.0f * (q.x * q.y + q.z * q.w);
    R[1][1] = 1.0f - 2.0f * (q.x * q.x + q.z * q.z);
    R[1][2] = 2.0f * (q.y * q.z - q.x * q.w);

    R[2][0] = 2.0f * (q.x * q.z - q.y * q.w);
    R[2][1] = 2.0f * (q.y * q.z + q.x * q.w);
    R[2][2] = 1.0f - 2.0f * (q.x * q.x + q.y * q.y);
}

void getWorldAcceleration(float world[3])
{
    float R[3][3];
    quaternionToMatrix(R);

    float body[3];
    body[0] = imu.getAccX();
    body[1] = imu.getAccY();
    body[2] = imu.getAccZ();

    // Transform body frame acceleration to world frame
    world[0] = R[0][0] * body[0] + R[0][1] * body[1] + R[0][2] * body[2];
    world[1] = R[1][0] * body[0] + R[1][1] * body[1] + R[1][2] * body[2];
    world[2] = R[2][0] * body[0] + R[2][1] * body[1] + R[2][2] * body[2];

    world[2] -= 9.80665f;
}

