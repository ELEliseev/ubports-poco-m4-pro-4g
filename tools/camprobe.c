/*
 * Show what the vendor camera HAL actually reports: how many cameras there are,
 * and the preview, video and still resolution lists.
 *
 * The app complains "viewfinder resolutions is not known yet" and the HAL
 * rejects parameter writes, so the question is whether the preview list is
 * empty on the HAL side or gets lost inside qtubuntu-camera.
 *
 * Build: aarch64-linux-gnu-gcc -o camprobe camprobe.c -lcamera
 *
 * Needs a sysroot with the same glibc as the phone (2.31): the host cross
 * compiler targets 2.34 and the binary then dies with "GLIBC_2.34 not found".
 * Add -static-libgcc, and take libstdc++.so.6 and libgcc_s.so.1 from the device.
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <stdlib.h>

struct CameraControl;

typedef void (*size_cb)(void *ctx, int width, int height);

extern int android_camera_get_number_of_devices(void);
extern struct CameraControl *android_camera_connect_by_id(int32_t id, void *listener);
extern void android_camera_disconnect(struct CameraControl *c);
extern void android_camera_dump_parameters(struct CameraControl *c);
extern void android_camera_enumerate_supported_preview_sizes(struct CameraControl *c, size_cb cb, void *ctx);
extern void android_camera_enumerate_supported_picture_sizes(struct CameraControl *c, size_cb cb, void *ctx);
extern void android_camera_enumerate_supported_video_sizes(struct CameraControl *c, size_cb cb, void *ctx);
extern void android_camera_set_preview_size(struct CameraControl *c, int w, int h);
extern void android_camera_get_preview_size(struct CameraControl *c, int *w, int *h);
extern void android_camera_set_picture_size(struct CameraControl *c, int w, int h);
extern void android_camera_get_picture_size(struct CameraControl *c, int *w, int *h);

static int counter;

static void on_size(void *ctx, int w, int h)
{
	(void) ctx;
	printf("    %d x %d\n", w, h);
	counter++;
}

/* The listener is really a table of callback pointers. We need none of
 * them, so hand over a generously sized block of zeroes. */
static unsigned char listener[1024];

int main(int argc, char **argv)
{
	int id = (argc > 1) ? atoi(argv[1]) : 0;
	int n = android_camera_get_number_of_devices();
	printf("cameras in the system: %d\n", n);
	if (n <= 0)
		return 1;

	printf("connecting to camera %d...\n", id);
	struct CameraControl *c = android_camera_connect_by_id(id, listener);
	if (!c) {
		printf("FAILED to connect\n");
		return 1;
	}
	printf("connected\n\n");

	printf("PREVIEW RESOLUTIONS:\n");
	counter = 0;
	android_camera_enumerate_supported_preview_sizes(c, on_size, NULL);
	printf("  total: %d%s\n\n", counter, counter ? "" : "   <-- EMPTY, there is the cause");

	printf("VIDEO RESOLUTIONS:\n");
	counter = 0;
	android_camera_enumerate_supported_video_sizes(c, on_size, NULL);
	printf("  total: %d\n\n", counter);

	printf("STILL RESOLUTIONS:\n");
	counter = 0;
	android_camera_enumerate_supported_picture_sizes(c, on_size, NULL);
	printf("  total: %d\n\n", counter);

	int w = 0, h = 0;
	android_camera_get_preview_size(c, &w, &h);
	printf("current preview: %d x %d\n", w, h);

	printf("trying to set preview 1280x720...\n");
	android_camera_set_preview_size(c, 1280, 720);
	w = h = 0; android_camera_get_preview_size(c, &w, &h);
	printf("  now: %d x %d  %s\n", w, h, (w == 1280 && h == 720) ? "ACCEPTED" : "REJECTED");

	android_camera_get_picture_size(c, &w, &h);
	printf("current still: %d x %d\n", w, h);
	printf("trying to set still 1920x1080...\n");
	android_camera_set_picture_size(c, 1920, 1080);
	w = h = 0; android_camera_get_picture_size(c, &w, &h);
	printf("  now: %d x %d  %s\n\n", w, h, (w == 1920 && h == 1080) ? "ACCEPTED" : "REJECTED");

	printf("the full parameter string goes to the Android log:\n");
	android_camera_dump_parameters(c);

	sleep(1);
	android_camera_disconnect(c);
	return 0;
}
