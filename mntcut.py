#!/usr/bin/env python3
# mntcut.py -- by mntmn
# minimalist video editor based around a text file and ffmpeg
# license: GPLv3+
#
# to get started, put your transcoded source clips into a folder and create a file playlist.tsv with the format:
#
# 0 0 video1.mov
# 0 0 video2.mov
#
# then, start mntcut.py --project /your/project/folder
#
# keys:
#
# 1 2    prev/next clip
# , .    prev/next 1/25th second
# < >    prev/next second
# space  play
# s      pause
# i      set inpoint  (writes playlist.tsv)
# o      set outpoint (writes playlist.tsv)
# 0      generate render.sh
#
# to render your project, execute the generated render.sh. it expects a subfolder "trimmed" for storing the
# edited clips.
#
# you can open the playlist.tsv in a text editor (for example emacs with auto-revert-mode) and edit that
# in parallel to using this program, to duplicate and reorder clips. mntcut reloads the playlist on every
# clip change.
#
# structure and some code lifted from: http://docs.gstreamer.com/display/GstSDK/Basic+tutorial+5%3A+GUI+toolkit+integration

import sys
import gi
gi.require_version('Gst', '1.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GdkX11', '3.0')
gi.require_version('GstVideo', '1.0')
from gi.repository import Gst, Gtk, GLib, GdkX11, GstVideo, Gdk

import argparse
import os
cls = lambda: os.system('clear')

class Player(object):

    def __init__(self):
        cwd = os.getcwd()

        parser = argparse.ArgumentParser(description='Cut some video clips')
        parser.add_argument('--project', nargs=1, dest='workdir',
                            help='Specify a project working directory which contains your clips and playlist.tsv')
        parser.add_argument('--play', nargs='?', dest='videofile',
                            help='Play the given video file')

        args = parser.parse_args()
        print("Project:", args.workdir)
        
        Gtk.init(sys.argv)
        Gst.init(sys.argv)

        self.playbin = None
        self.playlist = []
        self.playlist_cur_idx = 0
        
        self.state = Gst.State.NULL
        self.duration = Gst.CLOCK_TIME_NONE

        self.media_dir = args.workdir[0]
        self.build_ui()

        if args.videofile:
            self.setup_video(Gst.filename_to_uri(args.videofile))
        else:
            self.read_playlist()
        # show the first video
        filename = self.get_video_file(0)
        self.setup_video(Gst.filename_to_uri(filename))

    def start(self):
        # register a function that GLib will call every second
        GLib.timeout_add_seconds(1, self.refresh_ui)

        # start the GTK main loop. we will not regain control until
        # Gtk.main_quit() is called
        Gtk.main()

        # free resources
        self.cleanup()

    def cleanup(self):
        if self.playbin:
            self.playbin.set_state(Gst.State.NULL)
            self.playbin = None

    def build_ui(self):
        main_window = Gtk.Window.new(Gtk.WindowType.TOPLEVEL)
        main_window.connect("delete-event", self.on_delete_event)

        video_window = Gtk.DrawingArea.new()
        video_window.set_can_focus(True)
        video_window.set_events(Gdk.EventMask.KEY_PRESS_MASK)
        video_window.set_double_buffered(False)
        video_window.connect("realize", self.on_realize)
        video_window.connect("draw", self.on_draw)
        video_window.connect("key-press-event", self.on_keypress)
        
        #play_button = Gtk.Button.new_from_stock(Gtk.STOCK_MEDIA_PLAY)
        #play_button.connect("clicked", self.on_play)

        #self.slider = Gtk.HScale.new_with_range(0, 100, 1)
        #self.slider.set_draw_value(False)
        #self.slider_update_signal_id = self.slider.connect(
        #    "value-changed", self.on_slider_changed)

        self.streams_list = Gtk.TextView.new()
        self.streams_list.set_editable(False)

        #controls = Gtk.HBox.new(False, 0)
        #controls.pack_start(self.slider, True, True, 0)

        main_hbox = Gtk.HBox.new(False, 0)
        main_hbox.pack_start(video_window, True, True, 0)
        #main_hbox.pack_start(self.streams_list, False, False, 2)

        main_box = Gtk.VBox.new(False, 0)
        main_box.pack_start(main_hbox, True, True, 0)
        # main_box.pack_start(controls, False, False, 0)

        main_window.add(main_box)
        main_window.set_default_size(800, 500)
        main_window.show_all()


    def setup_video(self, uri):
        
        if self.playbin:
            self.playbin.set_state(Gst.State.NULL)
            self.playbin = None
        
        self.playbin = Gst.ElementFactory.make("playbin", "playbin")
        if not self.playbin:
            print("ERROR: Could not create playbin.")
            sys.exit(1)

        self.playbin.set_property("uri", uri)

        # pass it to playbin, which implements XOverlay and will forward
        # it to the video sink
        self.playbin.set_window_handle(self.window_handle)
        # self.playbin.set_xwindow_id(self.window_handle)

        #self.playbin.connect("video-tags-changed", self.on_tags_changed)
        #self.playbin.connect("audio-tags-changed", self.on_tags_changed)
        #self.playbin.connect("text-tags-changed", self.on_tags_changed)
        
        #self.bus = self.playbin.get_bus()
        #self.bus.add_signal_watch()
        #self.bus.connect("message::error", self.on_error)
        #self.bus.connect("message::eos", self.on_eos)
        #self.bus.connect("message::state-changed", self.on_state_changed)
        #self.bus.connect("message::application", self.on_application_message)
        self.playbin.set_state(Gst.State.PAUSED)
    
    def read_playlist(self):
        cls()
        # format:
        # inpoint outpoint file.mov
        self.playlist = []
        f = open(self.media_dir+"/playlist.tsv", "r")
        i = 0
        for x in f:
            if self.playlist_cur_idx==i:
                print("--> ",x.rstrip())
            else:
                print("    ",x.rstrip())
            self.playlist.append(x.rstrip())
            i = i+1

    def write_playlist(self):
        text_file = open(self.media_dir+"/playlist.tsv", "w")
        text_file.write("\n".join(self.playlist))
        text_file.close()

    def write_render_cmd(self):
        trimmed_files=[]
        cmds=[]
        idx=0
        path_dict={}
        
        for x in self.playlist:
            print(x)
            parts = self.playlist[idx].split()
            in_sec = int(parts[0])/1000000000.0
            out_sec = int(parts[1])/1000000000.0
            len_sec = out_sec-in_sec
            path = self.media_dir+"/"+parts[2]
            trimmed_path = self.media_dir+"/trimmed/"+parts[2]
            if trimmed_path in path_dict:
                path_dict[trimmed_path] = path_dict[trimmed_path]+1
                trimmed_path=self.media_dir+"/trimmed/"+str(path_dict[trimmed_path])+"_"+parts[2]
            else:
                path_dict[trimmed_path] = 1
            
            cmd="ffmpeg -y -ss "+str(in_sec)+" -i '"+str(path)+"' -c copy -t "+str(len_sec)+" '"+trimmed_path+"'"
            cmds.append(cmd)
            trimmed_files.append("file '"+trimmed_path+"'")
            idx=idx+1
        
        merge_list = "\n".join(trimmed_files)
        
        text_file = open("merge_list.txt", "w")
        text_file.write(merge_list)
        text_file.close()
        
        cmd="ffmpeg -y -safe 0 -f concat -i merge_list.txt -codec copy output.mov"
        cmds.append(cmd)
        text_file = open("render.sh", "w")
        text_file.write("\n".join(cmds))
        text_file.close()
        
        print(merge_list)
        print(cmds)
        
    def get_video_file(self, idx):
        self.read_playlist()
        parts = self.playlist[idx].split()
        return self.media_dir+"/"+parts[2]
    
    def get_inpoint(self, idx):
        self.read_playlist()
        parts = self.playlist[idx].split()
        return int(parts[0])
    
    def get_outpoint(self, idx):
        self.read_playlist()
        parts = self.playlist[idx].split()
        return int(parts[1])

    def set_inpoint(self, idx, pos):
        parts = self.playlist[idx].split()
        parts[0] = str(pos)
        self.playlist[idx] = " ".join(parts)
        print("IN  ", self.playlist[idx])
        
    def set_outpoint(self, idx, pos):
        parts = self.playlist[idx].split()
        parts[1] = str(pos)
        self.playlist[idx] = " ".join(parts)
        print("OUT ",self.playlist[idx])

    def on_keypress(self, widget, event):
        #print("          Modifiers: ", event.state)
        print("      Key val, name: ", event.keyval, Gdk.keyval_name(event.keyval))

        if event.keyval == Gdk.KEY_comma or event.keyval == Gdk.KEY_less:
            rc, pos_int = self.playbin.query_position(Gst.Format.TIME)
            ival = 1.0
            if (event.state & Gdk.ModifierType.SHIFT_MASK):
                ival = 10.0
            newpos = pos_int - ival/25.0 * Gst.SECOND
            self.playbin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                     newpos)
            #print(newpos)
        elif event.keyval == Gdk.KEY_period or event.keyval == Gdk.KEY_greater:
            rc, pos_int = self.playbin.query_position(Gst.Format.TIME)
            ival = 1.0
            if (event.state & Gdk.ModifierType.SHIFT_MASK):
                ival = 10.0
            newpos = pos_int + ival/25.0 * Gst.SECOND
            self.playbin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                     newpos)
            #print(newpos)
        elif event.keyval == Gdk.KEY_space:
            self.playbin.set_state(Gst.State.PLAYING)
        elif event.keyval == Gdk.KEY_s:
            self.playbin.set_state(Gst.State.PAUSED)
        elif event.keyval == Gdk.KEY_0:
            self.write_render_cmd()
        elif event.keyval == Gdk.KEY_q:
            exit()
        elif event.keyval == Gdk.KEY_r:
            filename = self.get_video_file(self.playlist_cur_idx)
            self.setup_video(Gst.filename_to_uri(filename))
        elif event.keyval == Gdk.KEY_i:
            rc, pos_int = self.playbin.query_position(Gst.Format.TIME)
            self.set_inpoint(self.playlist_cur_idx,pos_int)
            self.write_playlist()
        elif event.keyval == Gdk.KEY_o:
            rc, pos_int = self.playbin.query_position(Gst.Format.TIME)
            self.set_outpoint(self.playlist_cur_idx,pos_int)
            self.write_playlist()
        elif event.keyval == Gdk.KEY_2:
            next=(self.playlist_cur_idx+1)%len(self.playlist)
            filename = self.get_video_file(next)
            self.setup_video(Gst.filename_to_uri(filename))
            self.playlist_cur_idx=next
            newpos = self.get_inpoint(next)
            self.playbin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                     newpos)
        elif event.keyval == Gdk.KEY_1:
            next=(self.playlist_cur_idx-1)%len(self.playlist)
            filename = self.get_video_file(next)
            self.setup_video(Gst.filename_to_uri(filename))
            self.playlist_cur_idx=next
            newpos = self.get_inpoint(next)
            self.playbin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                     newpos)


    # this function is called when the GUI toolkit creates the physical window
    # that will hold the video
    # at this point we can retrieve its handler and pass it to GStreamer
    # through the XOverlay interface
    def on_realize(self, widget):
        self.window = widget.get_window()
        self.window_handle = self.window.get_xid()

    # this function is called when the PLAY button is clicked
    def on_play(self, button):
        self.playbin.set_state(Gst.State.PLAYING)
        pass

    # this function is called when the PAUSE button is clicked
    def on_pause(self, button):
        self.playbin.set_state(Gst.State.PAUSED)
        pass

    # this function is called when the STOP button is clicked
    def on_stop(self, button):
        self.playbin.set_state(Gst.State.READY)
        pass

    # this function is called when the main window is closed
    def on_delete_event(self, widget, event):
        self.on_stop(None)
        Gtk.main_quit()

    # this function is called every time the video window needs to be
    # redrawn. GStreamer takes care of this in the PAUSED and PLAYING states.
    # in the other states we simply draw a black rectangle to avoid
    # any garbage showing up
    def on_draw(self, widget, cr):
        #if self.state < Gst.State.PAUSED:
        #    allocation = widget.get_allocation()
        #
        #    cr.set_source_rgb(0, 0, 0)
        #    cr.rectangle(0, 0, allocation.width, allocation.height)
        #    cr.fill()

        return False

    # this function is called periodically to refresh the GUI
    def refresh_ui(self):
        current = -1

        # we do not want to update anything unless we are in the PAUSED
        # or PLAYING states
        if self.state < Gst.State.PAUSED:
            return True

        return True

    # this function is called when new metadata is discovered in the stream
    def on_tags_changed(self, playbin, stream):
        # we are possibly in a GStreamer working thread, so we notify
        # the main thread of this event through a message in the bus
        self.playbin.post_message(
            Gst.Message.new_application(
                self.playbin,
                Gst.Structure.new_empty("tags-changed")))

    # this function is called when an error message is posted on the bus
    def on_error(self, bus, msg):
        err, dbg = msg.parse_error()
        print("ERROR:", msg.src.get_name(), ":", err.message)
        if dbg:
            print("Debug info:", dbg)

    # this function is called when an End-Of-Stream message is posted on the bus
    # we just set the pipeline to READY (which stops playback)
    def on_eos(self, bus, msg):
        print("End-Of-Stream reached")
        self.playbin.set_state(Gst.State.READY)

    # this function is called when the pipeline changes states.
    # we use it to keep track of the current state
    def on_state_changed(self, bus, msg):
        old, new, pending = msg.parse_state_changed()
        if not msg.src == self.playbin:
            # not from the playbin, ignore
            return

        self.state = new
        print("State changed from {0} to {1}".format(
            Gst.Element.state_get_name(old), Gst.Element.state_get_name(new)))

        if old == Gst.State.READY and new == Gst.State.PAUSED:
            # for extra responsiveness we refresh the GUI as soons as
            # we reach the PAUSED state
            self.refresh_ui()

    # extract metadata from all the streams and write it to the text widget
    # in the GUI
    def analyze_streams(self):
        # clear current contents of the widget
        buffer = ""
        
        # read some properties
        nr_video = self.playbin.get_property("n-video")
        nr_audio = self.playbin.get_property("n-audio")
        nr_text = self.playbin.get_property("n-text")

        for i in range(nr_video):
            tags = None
            # retrieve the stream's video tags
            tags = self.playbin.emit("get-video-tags", i)
            if tags:
                buffer=buffer+("video stream {0}\n".format(i))
                _, str = tags.get_string(Gst.TAG_VIDEO_CODEC)
                buffer=buffer+(
                    "  codec: {0}\n".format(
                        str or "unknown"))

        for i in range(nr_audio):
            tags = None
            # retrieve the stream's audio tags
            tags = self.playbin.emit("get-audio-tags", i)
            if tags:
                buffer=buffer+("\naudio stream {0}\n".format(i))
                ret, str = tags.get_string(Gst.TAG_AUDIO_CODEC)
                if ret:
                    buffer=buffer+(
                        "  codec: {0}\n".format(
                            str or "unknown"))

                ret, str = tags.get_string(Gst.TAG_LANGUAGE_CODE)
                if ret:
                    buffer=buffer+(
                        "  language: {0}\n".format(
                            str or "unknown"))

                ret, str = tags.get_uint(Gst.TAG_BITRATE)
                if ret:
                    buffer=buffer+(
                        "  bitrate: {0}\n".format(
                            str or "unknown"))

        for i in range(nr_text):
            tags = None
            # retrieve the stream's subtitle tags
            tags = self.playbin.emit("get-text-tags", i)
            if tags:
                buffer=buffer+("\nsubtitle stream {0}\n".format(i))
                ret, str = tags.get_string(Gst.TAG_LANGUAGE_CODE)
                if ret:
                    buffer=buffer+(
                        "  language: {0}\n".format(
                            str or "unknown"))

        print(buffer)

    # this function is called when an "application" message is posted on the bus
    # here we retrieve the message posted by the on_tags_changed callback
    def on_application_message(self, bus, msg):
        if msg.get_structure().get_name() == "tags-changed":
            # if the message is the "tags-changed", update the stream info in
            # the GUI
            self.analyze_streams()

if __name__ == '__main__':
    p = Player()
    p.start()
