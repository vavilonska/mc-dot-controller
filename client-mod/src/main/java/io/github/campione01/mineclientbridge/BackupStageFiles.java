package io.github.campione01.mineclientbridge;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.*;
import java.security.*;
import java.util.*;
import java.util.zip.*;
import static java.nio.file.StandardOpenOption.*;
import static java.nio.file.LinkOption.NOFOLLOW_LINKS;

/** Disk-only snapshot primitives. Caller owns save/drain/consistency and its checkpoint deadline. */
final class BackupStageFiles {
    @FunctionalInterface interface Checkpoint { void check(String phase, Path path) throws IOException; }
    static final Checkpoint NONE = (phase, path) -> {};
    /** Directory names end in '/', bytes=0 and sha256='-'; file names are relative slash paths. */
    record Member(String path, long bytes, String sha256) {}
    static final class Stage {
        private final Path directory, world;
        private final List<Member> members;
        private final byte[] manifest;
        private List<Member> metadata=List.of();
        private volatile boolean committed;
        private Stage(Path directory, List<Member> members) {
            this.directory=directory; this.world=directory.resolve("world"); this.members=List.copyOf(members);
            StringBuilder s=new StringBuilder("MDC-STAGE-1\tbase64url-utf8-path\tbytes\tsha256\n");
            for(Member m:members) s.append(Base64.getUrlEncoder().withoutPadding().encodeToString(m.path().getBytes(StandardCharsets.UTF_8)))
                .append('\t').append(m.bytes()).append('\t').append(m.sha256()).append('\n');
            manifest=s.toString().getBytes(StandardCharsets.UTF_8);
        }
        Path directory(){return directory;} Path world(){return world;} List<Member> members(){return members;}
        boolean committed(){return committed;}
    }
    private BackupStageFiles() {}
    static Stage copy(Path source, Path newPartial, Checkpoint check) throws IOException {
        Objects.requireNonNull(check); Path src=clean(source), dst=clean(newPartial);
        directories(src); directories(dst.getParent());
        if(!Files.getFileStore(dst.getParent()).supportsFileAttributeView("posix"))throw new IOException("POSIX sealing required");
        if(dst.startsWith(src)) throw new IOException("staging must be outside source");
        check.check("copy_begin",src); Files.createDirectory(dst); Path world=Files.createDirectory(dst.resolve("world"));
        List<Member> members=new ArrayList<>(); Map<String,BasicFileAttributes> originals=new HashMap<>();
        Files.walkFileTree(src,new SimpleFileVisitor<Path>() {
            @Override public FileVisitResult preVisitDirectory(Path dir,BasicFileAttributes a) throws IOException {
                check.check("copy_directory",dir); if(a.isSymbolicLink()||!a.isDirectory()) throw new IOException("non-directory: "+dir);
                if(!dir.equals(src)){String name=relative(src,dir)+"/"; Files.createDirectory(world.resolve(relative(src,dir))); members.add(new Member(name,0,"-"));}
                return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult visitFile(Path file,BasicFileAttributes a) throws IOException {
                check.check("copy_file",file); regular(file);
                if(file.equals(src.resolve("session.lock"))) return FileVisitResult.CONTINUE;
                String name=relative(src,file); Path target=world.resolve(name); MessageDigest digest=digest(); long count=0;
                try(FileChannel in=FileChannel.open(file,READ,NOFOLLOW_LINKS); FileChannel out=FileChannel.open(target,CREATE_NEW,WRITE,NOFOLLOW_LINKS)) {
                    ByteBuffer buffer=ByteBuffer.allocate(65536); int n;
                    while((n=in.read(buffer))!=-1){check.check("copy_chunk",file);buffer.flip();digest.update(buffer.asReadOnlyBuffer());count+=n;while(buffer.hasRemaining())out.write(buffer);buffer.clear();}
                    out.force(true);
                }
                BasicFileAttributes after=regular(file);
                if(count!=a.size()||after.size()!=a.size()||!after.lastModifiedTime().equals(a.lastModifiedTime())||!Objects.equals(a.fileKey(),after.fileKey()))
                    throw new IOException("source changed while copying: "+file);
                members.add(new Member(name,count,HexFormat.of().formatHex(digest.digest()))); originals.put(name,after); return FileVisitResult.CONTINUE;
            }
        });
        members.sort(Comparator.comparing(Member::path));check.check("copy_verify_source",src);
        if(!scan(src,true,check).equals(new TreeSet<>(members.stream().map(Member::path).toList())))throw new IOException("source members changed");
        for(var entry:originals.entrySet()){BasicFileAttributes a=entry.getValue(), b=regular(src.resolve(entry.getKey()));if(a.size()!=b.size()||!a.lastModifiedTime().equals(b.lastModifiedTime())||!Objects.equals(a.fileKey(),b.fileKey()))throw new IOException("source changed after copy: "+entry.getKey());}
        Stage stage=new Stage(dst,members);
        writeNew(dst.resolve("MANIFEST.tsv"),stage.manifest); forceDirectories(world); forceDirectory(dst);forceDirectory(dst.getParent());
        check.check("copy_finished",dst); return stage;
    }
    /** Call only after the native caller has verified its saved source snapshot. */
    static void commit(Stage stage, Checkpoint check) throws IOException {
        Objects.requireNonNull(check); synchronized(stage) {
            if(stage.committed) throw new IOException("stage already committed");
            check.check("commit_begin",stage.directory); verify(stage,check);
            List<Member> metadata=new ArrayList<>();
            for(String name:scan(stage.directory,false,check)){
                if(name.equals("world/")||name.startsWith("world/"))continue;
                if(name.equals("STAGE-COMMITTED")||name.equals("STAGE-COMMITTED.partial"))throw new IOException("reserved stage marker exists");
                Path file=stage.directory.resolve(name);metadata.add(new Member(name,name.endsWith("/")?0:Files.size(file),name.endsWith("/")?"-":hash(file,check)));
            }
            stage.metadata=List.copyOf(metadata);
            for(Member m:metadata)if(!m.path().endsWith("/"))try(FileChannel channel=FileChannel.open(stage.directory.resolve(m.path()),READ,NOFOLLOW_LINKS)){channel.force(true);}
            List<Path> paths; try(var stream=Files.walk(stage.directory)){paths=stream.filter(p->!p.equals(stage.directory)).sorted(Comparator.reverseOrder()).toList();}
            for(Path path:paths){check.check("commit_seal",path); readOnly(path);}
            check.check("commit_publish",stage.directory);
            Path marker=stage.directory.resolve("STAGE-COMMITTED");writeNew(marker,"MDC-STAGE-1\n".getBytes(StandardCharsets.UTF_8));readOnly(marker);
            readOnly(stage.directory);forceDirectory(stage.directory);stage.committed=true;
        }
    }
    /** newArchiveDirectory must not exist. No old archive/package is modified or removed. */
    static Path zip(Stage stage, Path newArchiveDirectory, Checkpoint check) throws IOException {
        Objects.requireNonNull(check); if(!stage.committed)throw new IOException("uncommitted stage");
        Path dir=clean(newArchiveDirectory); directories(dir.getParent());
        if(dir.startsWith(stage.directory))throw new IOException("archive must be outside stage");
        check.check("zip_begin",stage.directory); verify(stage,check);
        if(!Arrays.equals(Files.readAllBytes(regularPath(stage.directory.resolve("STAGE-COMMITTED"))),"MDC-STAGE-1\n".getBytes(StandardCharsets.UTF_8)))throw new IOException("stage commit marker changed");
        Set<String> sealed=new TreeSet<>();for(Member m:stage.members)sealed.add("world/"+m.path());for(Member m:stage.metadata)sealed.add(m.path());sealed.add("world/");sealed.add("STAGE-COMMITTED");
        if(!scan(stage.directory,false,check).equals(sealed))throw new IOException("sealed members changed");
        Files.createDirectory(dir);
        Path partial=dir.resolve("backup.zip.partial"), archive=dir.resolve("backup.zip"), complete=dir.resolve("COMPLETE"); boolean success=false;
        try {
            MessageDigest archiveDigest=digest();
            try(OutputStream raw=Files.newOutputStream(partial,CREATE_NEW,WRITE); ZipOutputStream zip=new ZipOutputStream(new DigestOutputStream(raw,archiveDigest),StandardCharsets.UTF_8)) {
                add(zip,"world/",null);
                for(Member member:stage.members)writeMember(zip,stage.world,member,"world/",check);
                for(Member member:stage.metadata)writeMember(zip,stage.directory,member,"",check);
                add(zip,"STAGE-COMMITTED","MDC-STAGE-1\n".getBytes(StandardCharsets.UTF_8));
            }
            try(FileChannel channel=FileChannel.open(partial,WRITE)){channel.force(true);}
            String hash=HexFormat.of().formatHex(archiveDigest.digest()); check.check("zip_publish",archive);
            Files.move(partial,archive,StandardCopyOption.ATOMIC_MOVE); forceDirectory(dir);forceDirectory(dir.getParent());
            Path marker=dir.resolve("COMPLETE.partial");
            writeNew(marker,("MDC-BACKUP-1\nsha256="+hash+"\nbytes="+Files.size(archive)+"\n").getBytes(StandardCharsets.UTF_8));
            check.check("zip_complete",complete); Files.move(marker,complete,StandardCopyOption.ATOMIC_MOVE); forceDirectory(dir); success=true;
            return archive;
        } finally {if(!success)Files.deleteIfExists(complete);}
    }
    private static void verify(Stage stage,Checkpoint check) throws IOException {
        directories(stage.directory);directories(stage.world);
        if(!Arrays.equals(Files.readAllBytes(regularPath(stage.directory.resolve("MANIFEST.tsv"))),stage.manifest))throw new IOException("manifest changed");
        Set<String> actual=scan(stage.world,false,check), expected=new TreeSet<>();
        for(Member m:stage.members){expected.add(m.path());if(!m.path().endsWith("/")&&Files.size(stage.world.resolve(m.path()))!=m.bytes())throw new IOException("stage size changed: "+m.path());}
        if(!actual.equals(expected))throw new IOException("stage members changed");
    }
    private static Set<String> scan(Path root,boolean source,Checkpoint check)throws IOException {
        Set<String> result=new TreeSet<>();
        Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
            @Override public FileVisitResult preVisitDirectory(Path p,BasicFileAttributes a)throws IOException{check.check("verify_directory",p);if(!p.equals(root))result.add(relative(root,p)+"/");return FileVisitResult.CONTINUE;}
            @Override public FileVisitResult visitFile(Path p,BasicFileAttributes a)throws IOException{check.check("verify_member",p);regular(p);if(!(source&&p.equals(root.resolve("session.lock"))))result.add(relative(root,p));return FileVisitResult.CONTINUE;}
        });return result;
    }
    private static void writeMember(ZipOutputStream zip,Path root,Member member,String prefix,Checkpoint check)throws IOException {
        Path file=root.resolve(member.path());check.check("zip_member",file);ZipEntry entry=new ZipEntry(prefix+member.path());entry.setTime(0);zip.putNextEntry(entry);
        if(!member.path().endsWith("/")) {
            regular(file);MessageDigest digest=digest();long count=0;
            try(InputStream in=Channels.newInputStream(FileChannel.open(file,READ,NOFOLLOW_LINKS))){byte[] b=new byte[65536];int n;
                while((n=in.read(b))!=-1){check.check("zip_chunk",file);zip.write(b,0,n);digest.update(b,0,n);count+=n;}}
            if(count!=member.bytes()||!HexFormat.of().formatHex(digest.digest()).equals(member.sha256()))throw new IOException("stage changed during ZIP: "+file);
        }zip.closeEntry();
    }

    private static Path clean(Path p){return p.toAbsolutePath().normalize();}
    private static String relative(Path root,Path p){return root.relativize(p).toString().replace(File.separatorChar,'/');}
    private static void directories(Path p)throws IOException {if(p==null)throw new IOException("missing parent");Path at=p.getRoot();for(Path part:p){at=at.resolve(part);if(!Files.isDirectory(at,NOFOLLOW_LINKS)||Files.isSymbolicLink(at))throw new IOException("not a plain directory: "+at);}}
    private static BasicFileAttributes regular(Path p)throws IOException{var a=Files.readAttributes(p,BasicFileAttributes.class,NOFOLLOW_LINKS);if(!a.isRegularFile()||a.isSymbolicLink())throw new IOException("not a regular file: "+p);return a;}
    private static Path regularPath(Path p)throws IOException{regular(p);return p;}
    private static MessageDigest digest(){try{return MessageDigest.getInstance("SHA-256");}catch(NoSuchAlgorithmException e){throw new AssertionError(e);}}
    private static String hash(Path p,Checkpoint check)throws IOException{regular(p);MessageDigest d=digest();try(InputStream in=Channels.newInputStream(FileChannel.open(p,READ,NOFOLLOW_LINKS))){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1){check.check("hash_chunk",p);d.update(b,0,n);}}return HexFormat.of().formatHex(d.digest());}
    private static void writeNew(Path p,byte[] bytes)throws IOException{try(FileChannel c=FileChannel.open(p,CREATE_NEW,WRITE,NOFOLLOW_LINKS)){ByteBuffer b=ByteBuffer.wrap(bytes);while(b.hasRemaining())c.write(b);c.force(true);}}
    private static void add(ZipOutputStream z,String name,byte[] content)throws IOException{ZipEntry e=new ZipEntry(name);e.setTime(0);z.putNextEntry(e);if(content!=null)z.write(content);z.closeEntry();}
    private static void readOnly(Path p)throws IOException{var permissions=Files.getPosixFilePermissions(p,NOFOLLOW_LINKS);permissions.removeAll(Set.of(PosixFilePermission.OWNER_WRITE,PosixFilePermission.GROUP_WRITE,PosixFilePermission.OTHERS_WRITE));Files.setPosixFilePermissions(p,permissions);}
    private static void forceDirectory(Path p)throws IOException{try(FileChannel c=FileChannel.open(p,READ)){c.force(true);}}
    private static void forceDirectories(Path root)throws IOException{try(var paths=Files.walk(root)){for(Path p:paths.filter(x->Files.isDirectory(x,NOFOLLOW_LINKS)).sorted(Comparator.reverseOrder()).toList())forceDirectory(p);}}
}
