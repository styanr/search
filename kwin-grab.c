#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <gio/gio.h>
#include <gio/gunixfdlist.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static guint32 lookup_u32(GVariant *dict, const char *key) {
    guint32 v = 0;
    g_variant_lookup(dict, key, "u", &v);
    return v;
}

int main(void) {
    GError *err = NULL;
    GDBusConnection *bus = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, &err);
    if (!bus) {
        fprintf(stderr, "kwin-grab: %s\n", err->message);
        return 1;
    }

    int fds[2];
    if (pipe2(fds, O_CLOEXEC) != 0) {
        perror("kwin-grab: pipe");
        return 1;
    }
    GUnixFDList *fd_list = g_unix_fd_list_new_from_array(&fds[1], 1);

    GVariantBuilder opts;
    g_variant_builder_init(&opts, G_VARIANT_TYPE("a{sv}"));
    g_variant_builder_add(&opts, "{sv}", "include-cursor", g_variant_new_boolean(FALSE));
    g_variant_builder_add(&opts, "{sv}", "native-resolution", g_variant_new_boolean(TRUE));

    GVariant *reply = g_dbus_connection_call_with_unix_fd_list_sync(
        bus, "org.kde.KWin", "/org/kde/KWin/ScreenShot2", "org.kde.KWin.ScreenShot2",
        "CaptureWorkspace", g_variant_new("(a{sv}h)", &opts, 0),
        G_VARIANT_TYPE("(a{sv})"), G_DBUS_CALL_FLAGS_NONE, 5000, fd_list, NULL, NULL, &err);
    g_object_unref(fd_list);
    if (!reply) {
        fprintf(stderr, "kwin-grab: %s\n", err->message);
        return 1;
    }

    GVariant *results = g_variant_get_child_value(reply, 0);
    guint32 width = lookup_u32(results, "width");
    guint32 height = lookup_u32(results, "height");
    guint32 stride = lookup_u32(results, "stride");
    guint32 format = lookup_u32(results, "format");
    double scale = 1.0;
    g_variant_lookup(results, "scale", "d", &scale);

    size_t size = (size_t)stride * height;
    if (size == 0) {
        fprintf(stderr, "kwin-grab: unexpected reply %s\n", g_variant_print(results, TRUE));
        return 1;
    }
    unsigned char *buf = malloc(size);
    size_t got = 0;
    while (got < size) {
        ssize_t n = read(fds[0], buf + got, size - got);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            break;
        got += (size_t)n;
    }
    if (got != size) {
        fprintf(stderr, "kwin-grab: short read (%zu of %zu bytes)\n", got, size);
        return 1;
    }

    printf("%u %u %u %u %g\n", width, height, stride, format, scale);
    fflush(stdout);
    for (size_t off = 0; off < size;) {
        ssize_t n = write(STDOUT_FILENO, buf + off, size - off);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            return 1;
        off += (size_t)n;
    }
    return 0;
}
