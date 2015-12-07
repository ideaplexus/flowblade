"""
    Flowblade Movie Editor is a nonlinear video editor.
    Copyright 2012 Janne Liljeblad.

    This file is part of Flowblade Movie Editor <http://code.google.com/p/flowblade>.

    Flowblade Movie Editor is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    Flowblade Movie Editor is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with Flowblade Movie Editor. If not, see <http://www.gnu.org/licenses/>.
"""

from gi.repository import GObject, GLib
from gi.repository import Gtk, Gdk, GdkPixbuf
from gi.repository import GdkX11

import cairo
import locale
import mlt
import numpy as np
import os
import shutil
import subprocess
import sys

import appconsts
import cairoarea
import dialogutils
import editorstate
import editorpersistance
import gui
import guicomponents
import guiutils
import glassbuttons
import mltenv
import mltprofiles
import mlttransitions
import mltfilters
import positionbar
import respaths
import renderconsumer
import translations
import utils

import gmicplayer


MONITOR_WIDTH = 450
MONITOR_HEIGHT = 300 # initial value this gets changed when material is loaded
CLIP_FRAMES_DIR = "/clip_frames"
PREVIEW_FILE = "preview.png"

_window = None
_player = None
_frame_writer = None
_current_preview_surface = None
_current_dimensions = None
_current_fps = None

def launch_gmic():
    print "Launch gmic..."
    gui.save_current_colors()
    
    FLOG = open(utils.get_hidden_user_dir_path() + "log_gmic", 'w')
    subprocess.Popen([sys.executable, respaths.LAUNCH_DIR + "flowbladegmic"], stdin=FLOG, stdout=FLOG, stderr=FLOG)


def main(root_path, force_launch=False):
       
    gtk_version = "%s.%s.%s" % (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version())
    editorstate.gtk_version = gtk_version
    try:
        editorstate.mlt_version = mlt.LIBMLT_VERSION
    except:
        editorstate.mlt_version = "0.0.99" # magic string for "not found"
        
    # Set paths.
    respaths.set_paths(root_path)

    #c Init gmic tool session dirs
    if os.path.exists(get_session_folder()):
        shutil.rmtree(get_session_folder())
        
    os.mkdir(get_session_folder())
    
    init_clip_frames_dir()
    
    # Load editor prefs and list of recent projects
    editorpersistance.load()
    if editorpersistance.prefs.dark_theme == True:
        respaths.apply_dark_theme()

    # Init translations module with translations data
    translations.init_languages()
    translations.load_filters_translations()
    mlttransitions.init_module()

    # Init gtk threads
    Gdk.threads_init()
    Gdk.threads_enter()

    # Request dark them if so desired
    if editorpersistance.prefs.dark_theme == True:
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)

    repo = mlt.Factory().init()

    # Set numeric locale to use "." as radix, MLT initilizes this to OS locale and this causes bugs 
    locale.setlocale(locale.LC_NUMERIC, 'C')

    # Check for codecs and formats on the system
    mltenv.check_available_features(repo)
    renderconsumer.load_render_profiles()

    # Load filter and compositor descriptions from xml files.
    mltfilters.load_filters_xml(mltenv.services)
    mlttransitions.load_compositors_xml(mltenv.transitions)

    # Create list of available mlt profiles
    mltprofiles.load_profile_list()

    gui.load_current_colors()
    
    global _window
    _window = GmicWindow()
    
    #gui.set_theme_colors()
    _window.pos_bar.set_dark_bg_color()
    
    os.putenv('SDL_WINDOWID', str(_window.monitor.get_window().get_xid()))
    Gdk.flush()
        
    Gtk.main()
    Gdk.threads_leave()
    
def get_session_folder():
    return utils.get_hidden_user_dir_path() + appconsts.GMIC_DIR + "/test"

def get_clip_frames_dir():
    return get_session_folder() + CLIP_FRAMES_DIR

def get_current_frame_file():
    return get_clip_frames_dir() + "/frame" + str(_player.current_frame()) + ".png"

def get_preview_file():
    return get_session_folder() + PREVIEW_FILE
    
def init_clip_frames_dir():
    if os.path.exists(get_clip_frames_dir()):
        shutil.rmtree(get_clip_frames_dir())
    os.mkdir(get_clip_frames_dir())
    
def open_clip_dialog(callback):
    
    file_select = Gtk.FileChooserDialog(_("Select Image Media"), _window, Gtk.FileChooserAction.OPEN,
                                    (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                    Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

    file_select.set_default_response(Gtk.ResponseType.CANCEL)
    file_select.set_select_multiple(False)

    media_filter = utils.get_media_source_file_filter(False)
    all_filter = Gtk.FileFilter()
    all_filter.set_name(_("All files"))
    all_filter.add_pattern("*.*")
    file_select.add_filter(media_filter)
    file_select.add_filter(all_filter)

    if ((editorpersistance.prefs.open_in_last_opended_media_dir == True) 
        and (editorpersistance.prefs.last_opened_media_dir != None)):
        file_select.set_current_folder(editorpersistance.prefs.last_opened_media_dir)
    
    file_select.connect('response', callback)

    file_select.set_modal(True)
    file_select.show()

def _open_files_dialog_cb(file_select, response_id):
    filenames = file_select.get_filenames()
    file_select.destroy()

    if response_id != Gtk.ResponseType.OK:
        return
    if len(filenames) == 0:
        return

    new_profile = gmicplayer.set_current_profile(filenames[0])
    global _current_dimensions, _current_fps
    _current_dimensions = (new_profile.width(), new_profile.height(), 1.0)
    _current_fps = float(new_profile.frame_rate_num())/float(new_profile.frame_rate_den())

    global _player, _frame_writer
    _player = gmicplayer.GmicPlayer(filenames[0])
    _frame_writer = gmicplayer.FrameWriter(filenames[0])

    #display_aspect_num(self): return _mlt.Profile_display_aspect_num(self)
    #def display_aspect_den(self):
    _window.set_fps()
    _window.init_for_new_clip(filenames[0])
    _window.set_monitor_sizes()
    _player.create_sdl_consumer()
    _player.connect_and_start()

def show_preview():
    write_out_current_frame()
    
def write_out_current_frame():
    if os.path.exists(get_current_frame_file()):
        return

    _frame_writer.write_frame(get_clip_frames_dir() + "/", _player.current_frame())
    render_current_frame_preview()
    _window.preview_monitor.queue_draw()
    
def render_current_frame_preview():
    shutil.copyfile(get_current_frame_file(), get_preview_file())
    
    # gmic 00012.jpg -gimp_charcoal 65,70,170,0,1,0,50,70,255,255,255,0,0,0,0,0 -output gmic_test2.png
    script_str = "gmic " + get_current_frame_file() + " -gimp_charcoal 65,70,170,0,1,0,50,70,255,255,255,0,0,0,0,0 -output " +  get_preview_file()
    print script_str
    subprocess.call(script_str, shell=True)
     
    global _current_preview_surface
    _current_preview_surface = cairo.ImageSurface.create_from_png(get_preview_file())

class GmicWindow(Gtk.Window):
    def __init__(self):
        GObject.GObject.__init__(self)
        self.connect("delete-event", lambda w, e:_shutdown())

        app_icon = GdkPixbuf.Pixbuf.new_from_file(respaths.IMAGE_PATH + "flowblademedialinker.png")
        self.set_icon(app_icon)


        # Load media row
        load_button = Gtk.Button(_("Load Clip"))
        load_button.connect("clicked",
                            lambda w: self.load_button_clicked())
        self.media_info = Gtk.Label("video_clip.mpg   1920x 1080  25.0 fps")
        
        load_row = Gtk.HBox(False, 2)
        load_row.pack_start(load_button, False, False, 0)
        load_row.pack_start(guiutils.get_pad_label(24, 2), False, False, 0)
        load_row.pack_start(self.media_info, False, False, 0)
        load_row.pack_start(Gtk.Label(), True, True, 0)
        load_row.set_margin_bottom(4)

        #clip_panel = guiutils.get_named_frame(_("Preview"), load_row)

        # Clip monitor
        black_box = Gtk.EventBox()
        black_box.add(Gtk.Label())
        bg_color = Gdk.Color(red=0.0, green=0.0, blue=0.0)
        black_box.modify_bg(Gtk.StateType.NORMAL, bg_color)
        self.monitor = black_box  # This could be any GTK+ widget (that is not "windowless"), only its XWindow draw rect 
                                  # is used to position and scale SDL overlay that actually displays video.
        self.monitor.set_size_request(MONITOR_WIDTH, MONITOR_HEIGHT)

        left_vbox = Gtk.VBox(False, 0)
        left_vbox.pack_start(load_row, False, False, 0)
        left_vbox.pack_start(self.monitor, True, True, 0)

        self.preview_info = Gtk.Label(_("No Preview"))
        preview_info_row = Gtk.HBox()
        preview_info_row.pack_start(self.preview_info, False, False, 0)
        preview_info_row.pack_start(Gtk.Label(), True, True, 0)
        preview_info_row.set_margin_top(6)
        preview_info_row.set_margin_bottom(8)

        self.preview_monitor = cairoarea.CairoDrawableArea2(MONITOR_WIDTH, MONITOR_HEIGHT, self._draw_preview)

        right_vbox = Gtk.VBox(False, 2)
        #right_vbox.pack_start(Gtk.Label(), True, True, 0)
        #right_vbox.pack_start(guiutils.get_pad_label(10, 5), False, False, 0)
        right_vbox.pack_start(preview_info_row, False, False, 0)
        right_vbox.pack_start(self.preview_monitor, True, True, 0)


        # Monitors panel
        monitors_panel = Gtk.HBox(False, 2)
        monitors_panel.pack_start(left_vbox, False, False, 0)
        monitors_panel.pack_start(Gtk.Label(), True, True, 0)
        monitors_panel.pack_start(right_vbox, False, False, 0)

        # Control row
        self.tc_display = guicomponents.MonitorTCDisplay()
        self.tc_display.use_internal_frame = True
        self.tc_display.widget.set_valign(Gtk.Align.CENTER)
        self.tc_display.use_internal_fps = True
        
        self.pos_bar = positionbar.PositionBar(False)
        self.pos_bar.set_listener(self.position_listener)
        pos_bar_frame = Gtk.Frame()
        pos_bar_frame.add(self.pos_bar.widget)
        pos_bar_frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        pos_bar_frame.set_margin_top(5)
        pos_bar_frame.set_margin_bottom(4)
        pos_bar_frame.set_margin_left(6)
        pos_bar_frame.set_margin_right(2)
        
        self.control_buttons = glassbuttons.GmicButtons()
        
        preview_button = Gtk.Button(_("Preview"))
        preview_button.connect("clicked",
                            lambda w: self.preview_button_clicked())
                            
        control_panel = Gtk.HBox(False, 2)
        control_panel.pack_start(self.tc_display.widget, False, False, 0)
        control_panel.pack_start(pos_bar_frame, True, True, 0)
        control_panel.pack_start(self.control_buttons.widget, False, False, 0)
        control_panel.pack_start(guiutils.pad_label(2, 2), False, False, 0)
        control_panel.pack_start(preview_button, False, False, 0)

        preview_panel = Gtk.VBox(False, 2)
        preview_panel.pack_start(monitors_panel, False, False, 0)
        preview_panel.pack_start(control_panel, False, False, 0)
        preview_panel.set_margin_bottom(8)

        # Script area
        self.preset_label = Gtk.Label("Preset Script:")
        
        self.preset_select = Gtk.ComboBoxText()
        self.preset_select.set_tooltip_text(_("Select Preset G'Mic script"))
        self.preset_select.append_text("Gimp Charcoal")
        self.preset_select.set_active(0)

        preset_row = Gtk.HBox(False, 2)
        preset_row.pack_start(self.preset_label, False, False, 0)
        preset_row.pack_start(guiutils.pad_label(6, 12), False, False, 0)
        preset_row.pack_start(self.preset_select, False, False, 0)
        preset_row.pack_start(Gtk.Label(), True, True, 0)

        self.script_view = Gtk.TextView()
        self.script_view.set_sensitive(False)
        self.script_view.set_pixels_above_lines(2)
        self.script_view.set_left_margin(2)

        script_sw = Gtk.ScrolledWindow()
        script_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        script_sw.add(self.script_view)
        script_sw.set_size_request(MONITOR_WIDTH - 100, 150)

        self.out_view = Gtk.TextView()
        self.out_view.set_sensitive(False)
        self.out_view.set_pixels_above_lines(2)
        self.out_view.set_left_margin(2)

        out_sw = Gtk.ScrolledWindow()
        out_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        out_sw.add(self.out_view)
        out_sw.set_size_request(MONITOR_WIDTH - 150, 75)
        
        script_vbox = Gtk.VBox(False, 2)
        script_vbox.pack_start(preset_row, False, False, 0)
        script_vbox.pack_start(script_sw, True, True, 0)
        script_vbox.pack_start(out_sw, True, True, 0)

        #script_vbox = guiutils.get_named_frame(_("G'MIC Script"), script_vbox)
  
        # Outout area

        
        #output_vbox = Gtk.VBox(False, 2)
        #output_vbox.pack_start(out_sw, True, True, 0)
        #output_vbox.set_size_request(MONITOR_WIDTH - 150, 200)
    
        #output_vbox = guiutils.get_named_frame(_("Script Output"), output_vbox)

        # Render panel
        self.mark_in_info = Gtk.Label("Mark In: 00:00:00:00")
        self.mark_out_info = Gtk.Label("Mark Out: 00:00:02:00")
        self.length_info = Gtk.Label("Length: 52 frames")

        marks_row = Gtk.VBox(False, 2)
        marks_row.pack_start(guiutils.get_left_justified_box([self.mark_in_info]), True, True, 0)
        marks_row.pack_start(guiutils.get_left_justified_box([self.mark_out_info]), True, True, 0)
        marks_row.pack_start(guiutils.get_left_justified_box([self.length_info]), True, True, 0)
        #marks_row.set_margin_bottom(12)

        self.disk_info = Gtk.Label("Frames disk space est.: 768 MB")

        disk_row = Gtk.HBox(False, 2)
        disk_row.pack_start(guiutils.get_left_justified_box([self.disk_info]), False, False, 0)
        disk_row.pack_start(Gtk.Label(), True, True, 0)
        #disk_row.set_margin_bottom(6)

        self.out_folder = Gtk.FileChooserButton(_("Select Folder"))
        self.out_folder.set_action(Gtk.FileChooserAction.SELECT_FOLDER)
        self.out_folder.set_current_folder(os.path.expanduser("~") + "/")
        out_folder_row = guiutils.get_left_justified_box([Gtk.Label(label=_("Frames Folder:")), guiutils.pad_label(12, 2), self.out_folder])


        self.encode_check_label = Gtk.Label("Encode Video")
        self.encode_check = Gtk.CheckButton()
        self.encode_check.set_active(False)
        
        self.encode_settings_button = Gtk.Button(_("Encoding settings"))
        self.encode_desc = Gtk.Label()
        self.encode_desc.set_markup("<small>"+ "MPEG-2, 3000kbps" + "</small>")
        
        encode_row = Gtk.HBox(False, 2)
        encode_row.pack_start(self.encode_check, False, False, 0)
        encode_row.pack_start(self.encode_check_label, False, False, 0)
        encode_row.pack_start(guiutils.pad_label(48, 12), False, False, 0)
        encode_row.pack_start(self.encode_settings_button, False, False, 0)
        encode_row.pack_start(guiutils.pad_label(6, 12), False, False, 0)
        encode_row.pack_start(self.encode_desc, False, False, 0)
        #encode_row.pack_start(self.encode_settings_button, False, False, 0)
        encode_row.pack_start(Gtk.Label(), True, True, 0)
        encode_row.set_margin_bottom(6)

        self.file_name_label = Gtk.Label(_("Name:"))
        self.movie_name = Gtk.Entry()
        self.movie_name.set_text("movie")
        self.extension_label = Gtk.Label(".mpg")
        
        
        video_file_row = Gtk.HBox(False, 2)
        video_file_row.pack_start(self.file_name_label, False, False, 0)
        video_file_row.pack_start(self.movie_name, False, False, 0)
        video_file_row.pack_start(self.extension_label, False, False, 0)
        video_file_row.pack_start(Gtk.Label(), True, True, 0)
        
        self.render_status_info = Gtk.Label()
        self.render_status_info.set_markup("<small>"+ "52 frames, requiring 768MB dis space, video file: ../movie.mpg" + "</small>")

        render_status_row = Gtk.HBox(False, 2)
        render_status_row.pack_start(self.render_status_info, False, False, 0)
        render_status_row.pack_start(Gtk.Label(), True, True, 0)
        render_status_row.set_margin_bottom(6)

        self.render_progress_bar = Gtk.ProgressBar()
        stop_button = Gtk.Button(_("Stop"))
        render_button = Gtk.Button(_("Render"))

        render_row = Gtk.HBox(False, 2)
        render_row.pack_start(self.render_progress_bar, True, True, 0)
        render_row.pack_start(stop_button, False, False, 0)
        render_row.pack_start(render_button, False, False, 0)

        render_vbox = Gtk.VBox(False, 2)
        render_vbox.pack_start(marks_row, False, False, 0)
        render_vbox.pack_start(Gtk.Label(), True, True, 0)
        render_vbox.pack_start(encode_row, False, False, 0)
        #render_vbox.pack_start(video_file_row, False, False, 0)
        render_vbox.pack_start(Gtk.Label(), True, True, 0)
        render_vbox.pack_start(out_folder_row, False, False, 0)
        render_vbox.pack_start(Gtk.Label(), True, True, 0)
        render_vbox.pack_start(render_status_row, False, False, 0)
        render_vbox.pack_start(render_row, False, False, 0)
        render_vbox.pack_start(guiutils.pad_label(24, 24), False, False, 0)

        
        #render_vbox.set_size_request(MONITOR_WIDTH, 200)
    
        #render_vbox = guiutils.get_named_frame(_("Render"), render_vbox)
        
        # Script work panel
        script_work_panel = Gtk.HBox(False, 2)
        script_work_panel.pack_start(script_vbox, False, False, 0)
        script_work_panel.pack_start(guiutils.pad_label(12, 2), False, False, 0)
        script_work_panel.pack_start(render_vbox, True, True, 0)

        load_script = Gtk.Button(_("Load Script"))
        #load_layers.connect("clicked", lambda w:self._load_layers_pressed())
        save_script = Gtk.Button(_("Save Script"))
        #save_layers.connect("clicked", lambda w:self._save_layers_pressed())

        info_b = guiutils.get_sized_button(_("Info"), 150, 32)
        exit_b = guiutils.get_sized_button(_("Close"), 150, 32)
        #exit_b.connect("clicked", lambda w:close_titler())
        #save_titles_b = guiutils.get_sized_button(_("Save Title Graphic"), 150, 32)
        #save_titles_b.connect("clicked", lambda w:self._save_title_pressed())
        
        editor_buttons_row = Gtk.HBox()
        editor_buttons_row.pack_start(load_script, False, False, 0)
        editor_buttons_row.pack_start(save_script, False, False, 0)
        editor_buttons_row.pack_start(Gtk.Label(), True, True, 0)
        #editor_buttons_row.pack_start(keep_label, False, False, 0)
        #editor_buttons_row.pack_start(self.keep_layers_check, False, False, 0)
        #editor_buttons_row.pack_start(guiutils.pad_label(24, 2), False, False, 0)
        #editor_buttons_row.pack_start(open_label, False, False, 0)
        #editor_buttons_row.pack_start(self.open_in_current_check, False, False, 0)
        #editor_buttons_row.pack_start(guiutils.pad_label(24, 2), False, False, 0)
        editor_buttons_row.pack_start(info_b, False, False, 0)
        editor_buttons_row.pack_start(guiutils.pad_label(96, 2), False, False, 0)
        editor_buttons_row.pack_start(exit_b, False, False, 0)

        
        # Build window
        pane = Gtk.VBox(False, 2)
        #pane.pack_start(clip_panel, False, False, 0)
        #pane.pack_start(guiutils.get_pad_label(2, 12), False, False, 0)
        
        #pane.pack_start(monitors_panel, False, False, 0)
        pane.pack_start(preview_panel, False, False, 0)
        #pane.pack_start(guiutils.get_pad_label(2, 12), False, False, 0)
        pane.pack_start(script_work_panel, False, False, 0)
        #pane.pack_start(guiutils.get_pad_label(2, 12), False, False, 0)
        pane.pack_start(editor_buttons_row, False, False, 0)

        align = guiutils.set_margins(pane, 12, 12, 12, 12)

        # Set pane and show window
        self.add(align)
        self.set_title(_("G'MIC Effects"))
        self.set_position(Gtk.WindowPosition.CENTER)
        self.show_all()
        self.set_resizable(False)
        self.set_active_state(False)

    def init_for_new_clip(self, clip_path):
        self.clip_path = clip_path
        self.set_active_state(True)
        self.pos_bar.update_display_from_producer(_player.producer)
    
    def load_button_clicked(self):
        open_clip_dialog(_open_files_dialog_cb)

    def preview_button_clicked(self):
        show_preview()

    def set_active_state(self, active):
        self.monitor.set_sensitive(active)
        self.pos_bar.widget.set_sensitive(active)

    def set_fps(self):
        self.tc_display.fps = _current_fps
        
    def position_listener(self, normalized_pos, length):
        frame = normalized_pos * length
        #self.tc_display.set_frame(int(frame))
        self.pos_bar.widget.queue_draw()

    def _draw_preview(self, event, cr, allocation):
        x, y, w, h = allocation

        if _current_preview_surface != None:
            width, height, pixel_aspect = _current_dimensions
            scale = float(MONITOR_WIDTH) / float(width)
            print "scale", scale
            cr.scale(scale * pixel_aspect, scale)
            cr.set_source_surface(_current_preview_surface, 0, 0)
            cr.paint()
        else:
            cr.set_source_rgb(0.5, 0.5, 0.5)
            cr.rectangle(0, 0, w, h)
            cr.fill()

    def set_monitor_sizes(self):
        w, h, pixel_aspect = _current_dimensions
        new_height = MONITOR_WIDTH * (float(h)/float(w)) * pixel_aspect
        self.monitor.set_size_request(MONITOR_WIDTH, new_height)
        self.preview_monitor.set_size_request(MONITOR_WIDTH, new_height)

        
        
