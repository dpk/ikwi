$(function() {
    // doesn't work without the setTimeout for some reason
    // and only spottily works *with* it, grrr
    window.setTimeout(function() {
        var editFrame = document.getElementById('editframe'),
                source = editFrame.contentDocument.body.innerHTML,
                editor = new Squire(editFrame.contentDocument),
                imageUpload = null;
        editor.defaultBlockTag = 'P';
        
        editFrame.contentDocument.body.innerHTML = source;
        
        var resizeFrame = function() {
            var scroll = document.body.scrollTop;
            editFrame.height = ($(editFrame.contentDocument.body.parentNode).height());
            document.body.scrollTop = scroll;
        };
        
        var toggleButton = function(button, value) {
            var buttonElt = $(document.getElementById(button));
            if (value && !(buttonElt.hasClass('active'))) {
                buttonElt.addClass('active');
            } else if (!(value) && buttonElt.hasClass('active')) {
                buttonElt.removeClass('active');
            }
        };
        var setButtonState = function() {
            var blockStyleSelector = document.getElementById('blockstyle');
            if (editor.hasFormat('h2')) {
                $(blockStyleSelector).val('H2');
            } else if (editor.hasFormat('h3')) {
                $(blockStyleSelector).val('H3');
            } else {
                $(blockStyleSelector).val('P');
            }
            toggleButton('boldbutton', editor.hasFormat('strong'));
            toggleButton('italicbutton', editor.hasFormat('em'));
            toggleButton('linkbutton', editor.hasFormat('a'));
            
            toggleButton('ulbutton', editor.hasFormat('ul'));
            toggleButton('olbutton', editor.hasFormat('ol'));
        };
        
        var addTag = function(tagName) {
            return function(e) {
                e.preventDefault();
                if (editor.hasFormat(tagName)) {
                    editor.changeFormat(null, {tag: tagName});
                } else {
                    editor.changeFormat({tag: tagName});
                }
                editor.focus();
            };
        }; 
        $('#boldbutton').click(addTag('strong'));
        $('#italicbutton').click(addTag('em'));
        $('#blockstyle').change(function(e) {
            editor.removeList();
            var newTag = $(e.target).val(),
                    newFragment = new DocumentFragment();
            
            editor.modifyBlocks(function(fragment) {
                _.each(fragment.childNodes, function(node) {
                    var elt = document.createElement(newTag);
                    elt.innerHTML = node.innerHTML;
                    newFragment.appendChild(elt);
                });
                return newFragment;
            });
            
            editor.focus();
        });
        $('#ulbutton').click(function() {
            if (editor.hasFormat('ul')) {
                editor.removeList();
            } else {
                editor.makeUnorderedList();
            }
        });
        $('#olbutton').click(function() {
            if (editor.hasFormat('ol')) {
                editor.removeList();
            } else {
                editor.makeOrderedList();
            }
        });
        
        var setHeaderImage = function(file) {
            reader = new FileReader();

            reader.addEventListener('loadend', function() {
                $('.headerimage').removeClass('unfilled');
                var img = $('<img />');
                img.attr('src', reader.result);
                $('.headerimage').empty().append(img);
            });
            reader.readAsDataURL(file);
            imageUpload = file;
        };
        editor.addEventListener('input', function(e) {
            window.setTimeout(function() { resizeFrame() }, 0);
        });
        
        editor.addEventListener('pathChange', function(e) {
            setButtonState();
        });
        
        $('.headerimage').on('click', function() {
            var fileSelector = $('<input type=file>');
            fileSelector.on('change', function() {
                setHeaderImage(fileSelector.get(0).files[0]);
            });
            fileSelector.trigger('click');
        });
        $('.headerimage').on('dragover', function(e) { e.stopPropagation(); e.preventDefault(); });
        $('.headerimage').on('drop', function(e) {
            e.preventDefault();
            var files = e.originalEvent.dataTransfer.files,
                    file = files[0];
            setHeaderImage(file);
        });
        
        $('#savebutton').click(function() {
            var formData = new FormData();
            formData.append('title', $('#titlefield').val());
            formData.append('oldtitle', $('#oldtitle').val());
            formData.append('content', editor.getHTML());
            if (imageUpload) {
                formData.append('headerimage', imageUpload);
            }
            
            var request = new XMLHttpRequest();
            request.addEventListener('load', function() { window.location = window.location.pathname; });
            request.open("POST", window.location.pathname);
            request.send(formData);
        });
        
        // initialize
        resizeFrame();
        setButtonState();
    }, 100);
});
