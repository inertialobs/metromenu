/*
 * Windows 10 style start menu - Xfce panel plugin.
 *
 * Xfce only: this implements the libxfce4panel ABI (xfce_panel_module_construct)
 * and cannot be loaded by the LXQt panel, which uses its own Qt plugin ABI
 * (ILxQtPanelPlugin).  On LXQt add the start menu as a "Custom Command" widget
 * instead - see scripts/integrate-panel.sh.
 *
 * A thin panel button that toggles the metromenu application.  When an
 * instance is already running it is asked to toggle over D-Bus; otherwise the
 * program is spawned and anchored to this button so the popup appears right
 * next to it.
 */

#include <libxfce4panel/libxfce4panel.h>
#include <gtk/gtk.h>
#include <gio/gio.h>

#define METROMENU_APP_ID    "org.metromenu.MetroMenu"
#define METROMENU_APP_PATH  "/org/metromenu/MetroMenu"
#define METROMENU_PROGRAM   "metromenu"
#define METROMENU_ICON      "metromenu"

static gboolean
metromenu_activate_running_instance (void)
{
    GError *error = NULL;
    GDBusConnection *connection;
    GVariant *reply;

    connection = g_bus_get_sync (G_BUS_TYPE_SESSION, NULL, &error);
    if (connection == NULL)
    {
        g_clear_error (&error);
        return FALSE;
    }

    reply = g_dbus_connection_call_sync (connection,
                                         METROMENU_APP_ID,
                                         METROMENU_APP_PATH,
                                         "org.gtk.Application",
                                         "Activate",
                                         g_variant_new ("(a{sv})", NULL),
                                         NULL,
                                         G_DBUS_CALL_FLAGS_NO_AUTO_START,
                                         500,
                                         NULL,
                                         &error);
    g_object_unref (connection);

    if (reply != NULL)
    {
        g_variant_unref (reply);
        return TRUE;
    }

    g_clear_error (&error);
    return FALSE;
}

static gchar *
metromenu_find_program (void)
{
    gchar *program;
    const gchar *home;

    /* The panel's plugin process usually does not have ~/.local/bin in its
     * PATH, so look there explicitly as well. */
    program = g_find_program_in_path (METROMENU_PROGRAM);
    if (program != NULL)
        return program;

    home = g_get_home_dir ();
    if (home != NULL)
    {
        gchar *candidate = g_build_filename (home, ".local", "bin", METROMENU_PROGRAM, NULL);
        if (g_file_test (candidate, G_FILE_TEST_IS_EXECUTABLE))
            return candidate;
        g_free (candidate);
    }

    return g_strdup ("/usr/local/bin/" METROMENU_PROGRAM);
}

static const gchar *
metromenu_pick_icon (void)
{
    /* Prefer the icon theme's start-menu icon so the button matches the rest
     * of the desktop (e.g. the Windows 10 theme ships it as start-here). */
    static const gchar *candidates[] = {
        "ubuntu-logo", "start-here", "gnome-main-menu", METROMENU_ICON, NULL
    };
    GtkIconTheme *theme = gtk_icon_theme_get_default ();
    guint i;

    for (i = 0; candidates[i] != NULL; i++)
    {
        if (gtk_icon_theme_has_icon (theme, candidates[i]))
            return candidates[i];
    }
    return METROMENU_ICON;
}

static void
metromenu_spawn (GtkWidget *button)
{
    GError *error = NULL;
    gchar *program;
    gchar *anchor;
    gchar *argv[3];
    gint x = 0, y = 0, w = 0, h = 0;
    GdkWindow *window;

    program = metromenu_find_program ();
    if (program == NULL || !g_file_test (program, G_FILE_TEST_IS_EXECUTABLE))
    {
        g_warning ("metromenu: program not found - run scripts/install.sh");
        g_free (program);
        return;
    }

    window = gtk_widget_get_window (button);
    if (window != NULL)
    {
        gdk_window_get_origin (window, &x, &y);
        w = gtk_widget_get_allocated_width (button);
        h = gtk_widget_get_allocated_height (button);
    }

    anchor = g_strdup_printf ("--anchor=%d,%d,%d,%d", x, y, w, h);
    argv[0] = program;
    argv[1] = anchor;
    argv[2] = NULL;

    if (!g_spawn_async (NULL, argv, NULL,
                        G_SPAWN_SEARCH_PATH | G_SPAWN_DO_NOT_REAP_CHILD,
                        NULL, NULL, NULL, &error))
    {
        g_warning ("metromenu: failed to launch: %s", error->message);
        g_clear_error (&error);
    }

    g_free (anchor);
    g_free (program);
}

static gboolean
metromenu_button_pressed (GtkWidget      *button,
                      GdkEventButton *event,
                      gpointer        user_data)
{
    (void) user_data;
    if (event->button == 1)
    {
        /* Act on press, not on release: clicking the panel button makes the
         * menu lose focus first, so we must toggle before it auto-closes. */
        if (!metromenu_activate_running_instance ())
            metromenu_spawn (button);
    }
    /* Let the button draw its normal pressed state. */
    return FALSE;
}

static gboolean
metromenu_size_changed (XfcePanelPlugin *plugin,
                    gint             size,
                    GtkWidget       *button)
{
    GtkWidget *image = gtk_bin_get_child (GTK_BIN (button));

    /* Use the configured icon size (e.g. 16/22/32), not the panel height:
     * requesting an arbitrary size makes some themes fall back to a scalable
     * icon that may differ from the fixed-size one. */
    if (image != NULL)
        gtk_image_set_pixel_size (GTK_IMAGE (image),
                                  xfce_panel_plugin_get_icon_size (plugin));

    /* Make the clickable button a square of the full panel size, like the
     * Whisker menu button, instead of hugging the icon. */
    gtk_widget_set_size_request (button, size, size);
    return TRUE;
}

static void
metromenu_construct (XfcePanelPlugin *plugin)
{
    GtkWidget *button;
    GtkWidget *image;

    xfce_panel_plugin_set_small (plugin, TRUE);

    button = xfce_panel_create_button ();
    gtk_widget_set_tooltip_text (button, "Windows 10 Start Menu");
    gtk_widget_set_name (button, "metromenu-button");

    image = gtk_image_new_from_icon_name (metromenu_pick_icon (), GTK_ICON_SIZE_BUTTON);
    gtk_image_set_pixel_size (GTK_IMAGE (image),
                              xfce_panel_plugin_get_icon_size (plugin));
    gtk_container_add (GTK_CONTAINER (button), image);
    gtk_container_add (GTK_CONTAINER (plugin), button);
    gtk_widget_show_all (button);

    g_signal_connect (button, "button-press-event", G_CALLBACK (metromenu_button_pressed), NULL);
    g_signal_connect (plugin, "size-changed", G_CALLBACK (metromenu_size_changed), button);

    xfce_panel_plugin_add_action_widget (plugin, button);
}

XFCE_PANEL_PLUGIN_REGISTER (metromenu_construct)
